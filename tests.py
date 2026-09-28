"""
Comprehensive business rule and workflow test suite for Q-Hold application.
Tests containment rules, separation of repair vs VI certification,
hold removal preconditions, and sequential approval workflows.
"""

import io
import os
import tempfile
import unittest
from werkzeug.datastructures import FileStorage

_TEST_STORAGE = tempfile.TemporaryDirectory(prefix='qhold-tests-')
os.environ['QHOLD_DATABASE_PATH'] = os.path.join(_TEST_STORAGE.name, 'qhold.db')
os.environ['QHOLD_UPLOAD_FOLDER'] = os.path.join(_TEST_STORAGE.name, 'uploads')

from app import create_app
from qhold.seed_data import seed_database
from qhold.database import get_db_connection
from qhold.services.hold_service import HoldService, ValidationError
from qhold.services.repair_inspection_service import RepairInspectionService
from qhold.services.procedure_service import ProcedureService
from qhold.services.approval_service import ApprovalService
from qhold.rich_text import sanitize_rich_text
from qhold.repositories.vehicle_repo import VehicleRepository
from qhold.repositories.procedure_repo import ProcedureRepository
from qhold.repositories.hold_repo import HoldRepository

class QHoldBusinessRuleTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        seed_database()

    def test_repair_completion_does_not_pass_vi(self):
        """CRITICAL: Completing a repair MUST NOT mark VI inspection as passed."""
        # Vehicle 10 in MS-QH-2026-001 is 'Not Started' and 'Pending'
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, vin, repair_status, vi_inspection_status FROM affected_vehicles WHERE hold_id = 'MS-QH-2026-001' AND repair_status = 'Not Started' LIMIT 1")
        v = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(v)
        self.assertEqual(v['repair_status'], 'Not Started')
        self.assertEqual(v['vi_inspection_status'], 'Pending')

        # Record repair as 'Completed'
        RepairInspectionService.record_repair(
            vehicle_id=v['id'],
            technician_name='Tester Technician',
            repair_status='Completed',
            steps_completed='All steps completed according to SOP',
            parts_used='Clip #99000M24120-001',
            torque_readings='9.5 Nm'
        )

        # Re-fetch vehicle
        updated = VehicleRepository.get_vehicle_by_id(v['id'])
        self.assertEqual(updated['repair_status'], 'Completed')
        # VI MUST NOT BE PASSED!
        self.assertNotEqual(updated['vi_inspection_status'], 'Passed')
        self.assertEqual(updated['vi_inspection_status'], 'Pending')

    def test_new_repair_invalidates_previous_vi_pass(self):
        """Any new repair work clears an earlier certification until VI rechecks it."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM affected_vehicles
            WHERE hold_id = 'MS-QH-2026-001' AND vi_inspection_status = 'Passed'
            LIMIT 1
        """)
        vehicle = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(vehicle)

        updated = RepairInspectionService.record_repair(
            vehicle_id=vehicle['id'],
            technician_name='Replacement Technician',
            repair_status='Completed',
            steps_completed='Rechecked connector seating and torque.'
        )
        self.assertEqual(updated['vi_inspection_status'], 'Pending')
        self.assertIsNone(updated['vi_inspector'])
        self.assertIsNone(updated['vi_date'])

    def test_repair_technician_cannot_pass_own_vi(self):
        """VI certification must remain independent from repair execution."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, repair_technician FROM affected_vehicles
            WHERE repair_status = 'Completed' LIMIT 1
        """)
        vehicle = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(vehicle)

        with self.assertRaises(ValidationError) as ctx:
            RepairInspectionService.record_vi_inspection(
                vehicle_id=vehicle['id'],
                inspector_name=vehicle['repair_technician'],
                result='Passed',
                checklist_results='All criteria passed.'
            )
        self.assertIn("cannot certify their own repair", str(ctx.exception))

    def test_vi_pass_prohibited_if_repair_incomplete(self):
        """CRITICAL: Cannot pass VI inspection if repair is not completed."""
        # Find an unrepaired vehicle
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, vin, repair_status FROM affected_vehicles WHERE repair_status != 'Completed' LIMIT 1")
        v = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(v)

        # Attempt to pass VI on unrepaired vehicle
        with self.assertRaises(ValidationError) as ctx:
            RepairInspectionService.record_vi_inspection(
                vehicle_id=v['id'],
                inspector_name='VI Inspector #01',
                result='Passed',
                checklist_results='All tests pass'
            )
        self.assertIn("cannot pass VI inspection", str(ctx.exception))

    def test_hold_removal_blocked_until_100_percent_repaired_and_vi_passed(self):
        """CRITICAL: Hold removal requires 100% vehicles repaired AND 100% VI passed."""
        # Hold 1 has incomplete repairs
        can_remove, blockers = HoldService.check_hold_removal_readiness('MS-QH-2026-001')
        self.assertFalse(can_remove)
        self.assertTrue(len(blockers) > 0)

        with self.assertRaises(ValidationError) as ctx:
            HoldService.remove_hold('MS-QH-2026-001', actor_name='Admin', removal_reason='Premature attempt')
        self.assertIn("Cannot remove quality hold", str(ctx.exception))

        # Hold 4 has 100% repaired and 100% VI passed
        can_remove_4, blockers_4 = HoldService.check_hold_removal_readiness('MS-QH-2026-004')
        self.assertTrue(can_remove_4, f"Hold 4 should be removable, blockers: {blockers_4}")

        success = HoldService.remove_hold('MS-QH-2026-004', actor_name='Admin', removal_reason='All 6 vehicles verified and certified.')
        self.assertTrue(success)

        # Verify hold is now marked Removed
        h4 = HoldRepository.get_hold_by_id('MS-QH-2026-004')
        self.assertEqual(h4['status'], 'Removed')
        self.assertEqual(h4['removal_reason'], 'All 6 vehicles verified and certified.')

    def test_sequential_approval_workflow(self):
        """CRITICAL: Multi-stage approval chain requires all stages before status is Approved."""
        # Create a new draft procedure
        proc_id = ProcedureService.create_procedure({
            'title': 'Test Procedure for Coolant Line Check',
            'description': 'Test scope description',
            'applicable_models': 'Grand Vitara',
            'repair_instructions': 'Step 1: Check fitting. Step 2: Torque bolt.',
            'inspection_criteria': 'Criteria 1: Leak check. Criteria 2: Torque check.'
        }, author='Lead Author')

        proc = ProcedureRepository.get_procedure_by_id(proc_id)
        self.assertEqual(proc['status'], 'Draft')
        self.assertEqual(proc['current_approval_level'], 0)

        # Submit for approval
        ProcedureService.submit_for_approval(proc_id, actor_name='Lead Author')
        proc = ProcedureRepository.get_procedure_by_id(proc_id)
        self.assertEqual(proc['status'], 'Pending Approval')
        self.assertEqual(proc['current_approval_level'], 1)

        # Stage 1 approval (QA Lead)
        res1 = ApprovalService.process_decision(
            procedure_id=proc_id,
            approver_name='QA Lead Mishra',
            approver_role='Quality Assurance Lead',
            decision='Approved',
            comments='Stage 1 verified'
        )
        self.assertEqual(res1['status'], 'Pending Approval')
        self.assertEqual(res1['next_level'], 2)

        # Stage 2 approval (Mfg Eng Manager)
        res2 = ApprovalService.process_decision(
            procedure_id=proc_id,
            approver_name='Mgr Sundaram',
            approver_role='Manufacturing Engineering Manager',
            decision='Approved',
            comments='Stage 2 verified'
        )
        self.assertEqual(res2['status'], 'Pending Approval')
        self.assertEqual(res2['next_level'], 3)

        # Stage 3 approval (Plant Quality Head - Final stage)
        res3 = ApprovalService.process_decision(
            procedure_id=proc_id,
            approver_name='Dr Tanaka',
            approver_role='Plant Quality Head',
            decision='Approved',
            comments='Stage 3 final executive authorization'
        )
        self.assertEqual(res3['status'], 'Approved')

        # Final verification in DB
        proc_final = ProcedureRepository.get_procedure_by_id(proc_id)
        self.assertEqual(proc_final['status'], 'Approved')

    def test_only_configured_approver_can_decide_current_stage(self):
        proc_id = ProcedureService.create_procedure({
            'title': 'Test Procedure for Stage Authorization',
            'description': 'Test scope description',
            'applicable_models': 'Grand Vitara',
            'repair_instructions': 'Step 1: inspect fitting. Step 2: secure bolt.',
            'inspection_criteria': 'Confirm fitting and torque.'
        }, author='Test Author')
        ProcedureService.submit_for_approval(proc_id, actor_name='Test Author')

        with self.assertRaises(ValidationError) as ctx:
            ApprovalService.process_decision(
                procedure_id=proc_id,
                approver_name='Unauthorised User',
                approver_role='Production Viewer',
                decision='Approved',
                comments='Attempted decision'
            )
        self.assertIn("Only the configured approver", str(ctx.exception))

    def test_pending_procedure_cannot_be_edited_during_approval(self):
        proc_id = ProcedureService.create_procedure({
            'title': 'Test Procedure Locked During Review',
            'description': 'Test scope description',
            'applicable_models': 'Grand Vitara',
            'repair_instructions': 'Step 1: inspect fitting. Step 2: secure bolt.',
            'inspection_criteria': 'Confirm fitting and torque.'
        }, author='Test Author')
        ProcedureService.submit_for_approval(proc_id, actor_name='Test Author')

        with self.assertRaises(ValidationError) as ctx:
            ProcedureService.update_procedure(
                proc_id,
                {
                    'title': 'Changed during review',
                    'repair_instructions': 'Modified repair instructions.',
                    'inspection_criteria': 'Modified verification criteria.'
                },
                actor_name='Test Author'
            )
        self.assertIn("cannot be edited", str(ctx.exception))

    def test_procedure_can_be_archived_outside_approval(self):
        procedure_id = ProcedureService.create_procedure({
            'title': 'Procedure ready for archive',
            'description': 'Test procedure body.',
            'applicable_models': 'Fictional model',
            'repair_instructions': 'Inspect and secure the fitting.',
            'inspection_criteria': 'Confirm correct fitment.'
        }, author='Test Author')
        self.assertTrue(ProcedureService.archive_procedure(procedure_id, 'Test Author'))
        archived = ProcedureRepository.get_procedure_by_id(procedure_id)
        self.assertEqual(archived['status'], 'Archived')

    def test_procedure_rich_text_is_sanitized(self):
        procedure_id = ProcedureService.create_procedure({
            'title': 'Rich text sanitization check',
            'description': 'Test procedure body.',
            'applicable_models': 'Fictional model',
            'repair_instructions': '<script>alert(1)</script><strong onclick="run()">Safe step</strong>',
            'inspection_criteria': 'Confirm the step.'
        }, author='Test Author')
        saved = ProcedureRepository.get_procedure_by_id(procedure_id)
        self.assertIsNotNone(saved)
        self.assertNotIn('<script', saved['repair_instructions'])
        self.assertNotIn('onclick', saved['repair_instructions'])
        self.assertIn('<strong>Safe step</strong>', saved['repair_instructions'])

        sanitized = sanitize_rich_text(
            '<script>alert(1)</script><strong onclick="run()">Safe</strong>'
            '<img src="x" onerror="run()">'
        )
        self.assertNotIn('<script', sanitized)
        self.assertNotIn('onclick', sanitized)
        self.assertNotIn('<img', sanitized)
        self.assertIn('<strong>Safe</strong>', sanitized)

    def test_file_upload_validation_and_preservation(self):
        """Test Word document and image upload, preservation, and rejection of invalid types."""
        proc = ProcedureRepository.get_all_procedures()[0]

        # Valid Word doc upload
        doc_file = FileStorage(
            stream=io.BytesIO(b"Fake Word Doc Content PK\x03\x04"),
            filename="Service_Bulletin_2026.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

        res = ProcedureService.save_attachment(proc['id'], doc_file)
        self.assertEqual(res['original_filename'], 'Service_Bulletin_2026.docx')
        self.assertEqual(res['file_type'], 'document')

        # Invalid file type (.exe)
        bad_file = FileStorage(stream=io.BytesIO(b"MZ executable"), filename="script.exe")
        with self.assertRaises(ValidationError) as ctx:
            ProcedureService.save_attachment(proc['id'], bad_file)
        self.assertIn("Unsupported file format", str(ctx.exception))

    def test_demo_role_restrictions_and_safe_role_redirect(self):
        with self.client.session_transaction() as flask_session:
            flask_session['demo_role'] = 'Production Viewer'

        denied = self.client.get('/procedures/new')
        self.assertEqual(denied.status_code, 403)

        switched = self.client.post('/set-role', data={
            'role': 'Procedure Author',
            'next': 'https://example.invalid/'
        })
        self.assertEqual(switched.status_code, 302)
        self.assertEqual(switched.headers['Location'], '/')

    def test_primary_sections_and_record_views_render(self):
        paths = [
            '/',
            '/about',
            '/procedures/',
            '/repair-inspection/',
            '/production/',
            '/approvals/',
            '/procedures/SOP-QH-2026-01',
            '/repair-inspection/holds/MS-QH-2026-001',
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(b'{%', response.data)
                self.assertNotIn(b'{{', response.data)
                self.assertIn(b'Maruti Suzuki Q-Hold', response.data)

    def test_flask_static_assets_are_available(self):
        assets = [
            '/static/css/main.css',
            '/static/css/responsive.css',
            '/static/js/interactions.js',
            '/static/img/E-vitara.png',
        ]
        for path in assets:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertGreater(len(response.data), 0)
                response.close()

    def test_templates_are_not_exposed_as_raw_static_files(self):
        response = self.client.get('/qhold/templates/home.html')
        self.assertEqual(response.status_code, 404)

if __name__ == '__main__':
    unittest.main()
