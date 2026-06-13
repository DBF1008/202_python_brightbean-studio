"""Tests for the persisted CSV bulk-import job (engine + views)."""

import csv
import io
import shutil
import tempfile
import zoneinfo
from datetime import datetime
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.csv_import import process_csv_import_job
from apps.composer.models import ContentCategory, CSVImportJob, PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

_TMP_MEDIA = tempfile.mkdtemp()


def _csv_text(header, rows):
    """Build a properly-quoted CSV string (header + data rows)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class CSVImportEngineTests(TestCase):
    """Direct tests of process_csv_import_job (no worker, like PublishEngine tests)."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="testpass123",
            tos_accepted_at=timezone.now(),
        )
        self.org = Organization.objects.create(name="Test Org")
        self.workspace = Workspace.objects.create(
            organization=self.org,
            name="Test Workspace",
            timezone="America/New_York",
        )
        self.youtube = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="youtube",
            account_platform_id="yt-1",
            account_name="YT Channel",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.tiktok = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="tiktok",
            account_platform_id="tt-1",
            account_name="TT Account",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )

    def _make_job(self, csv_text, mapping, total_rows):
        job = CSVImportJob.objects.create(
            workspace=self.workspace,
            uploaded_by=self.user,
            column_mapping=mapping,
            total_rows=total_rows,
            status=CSVImportJob.Status.PENDING,
        )
        job.file.save(f"import-{job.id}.csv", ContentFile(csv_text.encode("utf-8")), save=True)
        return job

    def test_happy_path_creates_posts_with_full_semantics(self):
        header = ["date", "platforms", "caption", "category", "tags"]
        rows = [
            ["2026-05-01", "youtube", "Hello world", "Educational", "a, b"],
            ["", "tiktok", "Second post", "", ""],
        ]
        job = self._make_job(_csv_text(header, rows), {"date": 0, "platforms": 1, "caption": 2, "category": 3, "tags": 4}, 2)

        process_csv_import_job(job)
        job.refresh_from_db()

        self.assertEqual(job.status, CSVImportJob.Status.COMPLETED)
        self.assertEqual(job.total_rows, 2)
        self.assertEqual(job.processed_rows, 2)
        self.assertEqual(job.result_summary["created"], 2)
        self.assertEqual(job.result_summary["errors"], 0)
        self.assertEqual(job.result_summary["warnings"], [])

        self.assertEqual(Post.objects.filter(workspace=self.workspace).count(), 2)

        # Scheduled row: localized to the workspace timezone, default 09:00.
        scheduled_post = Post.objects.get(caption="Hello world")
        expected = datetime(2026, 5, 1, 9, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York"))
        self.assertEqual(scheduled_post.scheduled_at, expected)
        self.assertEqual(scheduled_post.tags, ["a", "b"])
        self.assertEqual(scheduled_post.category.name, "Educational")
        yt_pp = PlatformPost.objects.get(post=scheduled_post)
        self.assertEqual(yt_pp.social_account, self.youtube)
        self.assertEqual(yt_pp.status, "scheduled")
        self.assertEqual(yt_pp.scheduled_at, expected)

        # Draft row: no date → draft, no schedule, no category.
        draft_post = Post.objects.get(caption="Second post")
        self.assertIsNone(draft_post.scheduled_at)
        self.assertIsNone(draft_post.category)
        tt_pp = PlatformPost.objects.get(post=draft_post)
        self.assertEqual(tt_pp.social_account, self.tiktok)
        self.assertEqual(tt_pp.status, "draft")

        # Category was created on demand.
        self.assertTrue(ContentCategory.objects.filter(workspace=self.workspace, name="Educational").exists())

    def test_per_row_error_isolation(self):
        header = ["date", "platforms", "caption"]
        rows = [
            ["2026-05-01", "youtube", "Valid caption"],  # row 2 → created
            ["", "youtube", ""],  # row 3 → empty caption → skipped
            ["not-a-date", "youtube", "Bad date row"],  # row 4 → strptime raises → isolated
        ]
        job = self._make_job(_csv_text(header, rows), {"date": 0, "platforms": 1, "caption": 2}, 3)

        process_csv_import_job(job)
        job.refresh_from_db()

        self.assertEqual(job.status, CSVImportJob.Status.COMPLETED)
        self.assertEqual(job.processed_rows, 3)
        self.assertEqual(job.result_summary["created"], 1)
        self.assertEqual(job.result_summary["errors"], 2)

        # Only the valid row produced a Post; the bad-date row rolled back fully.
        self.assertEqual(Post.objects.filter(workspace=self.workspace).count(), 1)
        self.assertTrue(Post.objects.filter(caption="Valid caption").exists())
        self.assertFalse(Post.objects.filter(caption="Bad date row").exists())

        warnings = job.result_summary["warnings"]
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("Row 3" in w and "caption is empty" in w for w in warnings))
        self.assertTrue(any(w.startswith("Row 4") for w in warnings))

    def test_unreadable_file_marks_job_failed(self):
        job = CSVImportJob.objects.create(
            workspace=self.workspace,
            uploaded_by=self.user,
            column_mapping={"caption": 0},
            total_rows=1,
            status=CSVImportJob.Status.PENDING,
        )
        # Invalid UTF-8 → decode raises → fatal for the job (no crash loop).
        job.file.save(f"import-{job.id}.csv", ContentFile(b"\xff\xfe\x00\x01"), save=True)

        process_csv_import_job(job)
        job.refresh_from_db()

        self.assertEqual(job.status, CSVImportJob.Status.FAILED)
        self.assertEqual(Post.objects.filter(workspace=self.workspace).count(), 0)
        self.assertIn("Could not read", job.result_summary["warnings"][0])

    def test_completed_job_is_not_reprocessed(self):
        header = ["caption"]
        rows = [["Should not be imported"]]
        job = self._make_job(_csv_text(header, rows), {"caption": 0}, 1)
        job.status = CSVImportJob.Status.COMPLETED
        job.result_summary = {"created": 5, "errors": 0, "warnings": []}
        job.save(update_fields=["status", "result_summary"])

        process_csv_import_job(job)
        job.refresh_from_db()

        self.assertEqual(job.status, CSVImportJob.Status.COMPLETED)
        self.assertEqual(job.result_summary["created"], 5)  # untouched
        self.assertEqual(Post.objects.filter(workspace=self.workspace).count(), 0)


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class CSVImportViewTests(TestCase):
    """Tests for the confirm (job creation + enqueue) and status (polling) views."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="testpass123",
            tos_accepted_at=timezone.now(),
        )
        self.org = Organization.objects.create(name="Test Org")
        self.workspace = Workspace.objects.create(organization=self.org, name="Test Workspace")
        OrgMembership.objects.create(user=self.user, organization=self.org, org_role=OrgMembership.OrgRole.OWNER)
        WorkspaceMembership.objects.create(
            user=self.user,
            workspace=self.workspace,
            workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
        )
        self.client.force_login(self.user)
        self.confirm_url = reverse("composer:csv_confirm_import", kwargs={"workspace_id": self.workspace.id})

    def _seed_session(self):
        session = self.client.session
        session[f"csv_import_{self.workspace.id}"] = {
            "headers": ["date", "platforms", "caption"],
            "rows": [["2026-05-01", "youtube", "Hi there"], ["", "youtube", "Second"]],
            "filename": "plan.csv",
        }
        session[f"csv_mapping_{self.workspace.id}"] = {"date": 0, "platforms": 1, "caption": 2}
        session.save()

    def test_confirm_creates_job_and_enqueues_task(self):
        self._seed_session()
        with patch("apps.composer.tasks.process_csv_import_job_task") as mock_task:
            response = self.client.post(self.confirm_url)

        self.assertEqual(response.status_code, 200)
        job = CSVImportJob.objects.get(workspace=self.workspace)
        self.assertEqual(job.status, CSVImportJob.Status.PENDING)
        self.assertEqual(job.total_rows, 2)
        self.assertEqual(job.uploaded_by, self.user)
        self.assertEqual(job.column_mapping, {"date": 0, "platforms": 1, "caption": 2})
        self.assertTrue(job.file.name)  # file persisted onto the job

        mock_task.assert_called_once_with(str(job.id))

        # Session wizard state is cleared — the job owns the data now.
        self.assertNotIn(f"csv_import_{self.workspace.id}", self.client.session)
        self.assertNotIn(f"csv_mapping_{self.workspace.id}", self.client.session)

        # Response is the polling progress partial pointing at the status URL.
        status_url = reverse(
            "composer:csv_import_status",
            kwargs={"workspace_id": self.workspace.id, "job_id": job.id},
        )
        body = response.content.decode()
        self.assertIn(status_url, body)
        self.assertIn("every 1500ms", body)

    def test_confirm_without_session_returns_400(self):
        response = self.client.post(self.confirm_url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CSVImportJob.objects.exists())

    def test_persisted_file_is_processable_end_to_end(self):
        """The job created by confirm can be processed straight from its file."""
        self._seed_session()
        SocialAccount.objects.create(
            workspace=self.workspace,
            platform="youtube",
            account_platform_id="yt-x",
            account_name="YT",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        with patch("apps.composer.tasks.process_csv_import_job_task"):
            self.client.post(self.confirm_url)
        job = CSVImportJob.objects.get(workspace=self.workspace)

        process_csv_import_job(job)
        job.refresh_from_db()

        self.assertEqual(job.status, CSVImportJob.Status.COMPLETED)
        self.assertEqual(job.processed_rows, 2)
        self.assertEqual(job.result_summary["created"], 2)
        self.assertEqual(Post.objects.filter(workspace=self.workspace).count(), 2)

    def _status_url(self, job):
        return reverse(
            "composer:csv_import_status",
            kwargs={"workspace_id": self.workspace.id, "job_id": job.id},
        )

    def test_status_shows_progress_then_completion(self):
        job = CSVImportJob.objects.create(
            workspace=self.workspace,
            uploaded_by=self.user,
            column_mapping={},
            total_rows=4,
            processed_rows=2,
            status=CSVImportJob.Status.PROCESSING,
        )
        url = self._status_url(job)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("csv-import-progress", body)
        self.assertIn("every 1500ms", body)  # still polling

        job.status = CSVImportJob.Status.COMPLETED
        job.result_summary = {"created": 3, "errors": 1, "warnings": ["Row 5: caption is empty"]}
        job.save(update_fields=["status", "result_summary"])

        response = self.client.get(url)
        body = response.content.decode()
        self.assertIn("Import Complete", body)
        self.assertNotIn("every 1500ms", body)  # polling stopped

    def test_status_failed_state_stops_polling(self):
        job = CSVImportJob.objects.create(
            workspace=self.workspace,
            uploaded_by=self.user,
            column_mapping={},
            total_rows=1,
            status=CSVImportJob.Status.FAILED,
            result_summary={"created": 0, "errors": 0, "warnings": ["Could not read CSV file: boom"]},
        )
        response = self.client.get(self._status_url(job))
        body = response.content.decode()
        self.assertIn("Import failed", body)
        self.assertNotIn("every 1500ms", body)

    def test_status_other_workspace_job_returns_404(self):
        other_org = Organization.objects.create(name="Other Org")
        other_ws = Workspace.objects.create(organization=other_org, name="Other WS")
        other_job = CSVImportJob.objects.create(
            workspace=other_ws,
            uploaded_by=self.user,
            column_mapping={},
            total_rows=1,
            status=CSVImportJob.Status.PROCESSING,
        )
        # Requested under self.workspace, but the job belongs to other_ws.
        url = reverse(
            "composer:csv_import_status",
            kwargs={"workspace_id": self.workspace.id, "job_id": other_job.id},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
