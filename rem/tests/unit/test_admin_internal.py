"""
Unit tests for admin internal endpoints.

Tests the kv_store rebuild endpoint without requiring database or SQS.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rem.api.routers.admin import (
    RebuildKVRequest,
    RebuildKVResponse,
    _submit_sqs_rebuild_job_sync,
    _validate_internal_secret,
    trigger_kv_rebuild,
)


class TestRebuildKVRequest:
    """Test the request model."""

    def test_defaults(self):
        req = RebuildKVRequest()
        assert req.user_id is None
        assert req.triggered_by == "api"
        assert req.timestamp is None

    def test_with_values(self):
        req = RebuildKVRequest(
            user_id="user123",
            triggered_by="pg_net_rem_lookup",
            timestamp="2025-01-01T00:00:00Z",
        )
        assert req.user_id == "user123"
        assert req.triggered_by == "pg_net_rem_lookup"
        assert req.timestamp == "2025-01-01T00:00:00Z"


class TestRebuildKVResponse:
    """Test the response model."""

    def test_sqs_response(self):
        resp = RebuildKVResponse(
            status="submitted",
            message="Rebuild job submitted to SQS queue",
            job_method="sqs",
        )
        assert resp.status == "submitted"
        assert resp.job_method == "sqs"

    def test_thread_response(self):
        resp = RebuildKVResponse(
            status="started",
            message="Rebuild started in background thread",
            job_method="thread",
        )
        assert resp.status == "started"
        assert resp.job_method == "thread"


class TestSubmitSQSRebuildJob:
    """Test SQS job submission logic."""

    def test_no_queue_url_returns_false(self):
        """Should return False when SQS queue URL not configured."""
        with patch("rem.api.routers.admin.settings") as mock_settings:
            mock_settings.sqs.queue_url = ""

            request = RebuildKVRequest(triggered_by="test")
            result = _submit_sqs_rebuild_job_sync(request)

            assert result is False

    def test_sqs_send_success(self):
        """Should return True when SQS message sent successfully."""
        with patch("rem.api.routers.admin.settings") as mock_settings:
            mock_settings.sqs.queue_url = "https://sqs.us-east-1.amazonaws.com/123/test-queue"
            mock_settings.sqs.region = "us-east-1"

            with patch("boto3.client") as mock_boto:
                mock_sqs = MagicMock()
                mock_sqs.send_message.return_value = {"MessageId": "msg-123"}
                mock_boto.return_value = mock_sqs

                request = RebuildKVRequest(
                    user_id="user123",
                    triggered_by="pg_net_test",
                )
                result = _submit_sqs_rebuild_job_sync(request)

                assert result is True
                mock_sqs.send_message.assert_called_once()

                # Verify message content
                call_args = mock_sqs.send_message.call_args
                assert call_args.kwargs["QueueUrl"] == mock_settings.sqs.queue_url
                assert "rebuild_kv_store" in call_args.kwargs["MessageBody"]

    def test_sqs_client_error_returns_false(self):
        """Should return False when SQS raises ClientError."""
        from botocore.exceptions import ClientError

        with patch("rem.api.routers.admin.settings") as mock_settings:
            mock_settings.sqs.queue_url = "https://sqs.us-east-1.amazonaws.com/123/test-queue"
            mock_settings.sqs.region = "us-east-1"

            with patch("boto3.client") as mock_boto:
                mock_sqs = MagicMock()
                mock_sqs.send_message.side_effect = ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
                    "SendMessage"
                )
                mock_boto.return_value = mock_sqs

                request = RebuildKVRequest(triggered_by="test")
                result = _submit_sqs_rebuild_job_sync(request)

                assert result is False


class TestValidateInternalSecret:
    """Test secret validation logic."""

    @pytest.mark.asyncio
    async def test_missing_header_raises_401(self):
        """Should raise 401 when X-Internal-Secret header is missing."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await _validate_internal_secret(None)

        assert exc_info.value.status_code == 401
        assert "Missing" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_invalid_secret_raises_401(self):
        """Should raise 401 when secret doesn't match."""
        from fastapi import HTTPException

        with patch("rem.api.routers.admin._get_internal_secret") as mock_get:
            mock_get.return_value = "correct-secret"

            with pytest.raises(HTTPException) as exc_info:
                await _validate_internal_secret("wrong-secret")

            assert exc_info.value.status_code == 401
            assert "Invalid" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_secret_returns_true(self):
        """Should return True when secret matches."""
        with patch("rem.api.routers.admin._get_internal_secret") as mock_get:
            mock_get.return_value = "correct-secret"

            result = await _validate_internal_secret("correct-secret")

            assert result is True

    @pytest.mark.asyncio
    async def test_no_secret_configured_raises_503(self):
        """Should raise 503 when secret not found in database."""
        from fastapi import HTTPException

        with patch("rem.api.routers.admin._get_internal_secret") as mock_get:
            mock_get.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await _validate_internal_secret("any-secret")

            assert exc_info.value.status_code == 503
            assert "not configured" in exc_info.value.detail


class TestTriggerKVRebuild:
    """Test the main endpoint handler."""

    @pytest.mark.asyncio
    async def test_sqs_success_returns_submitted(self):
        """Should return 'submitted' status when SQS succeeds."""
        with patch("rem.api.routers.admin._submit_sqs_rebuild_job") as mock_sqs:
            mock_sqs.return_value = True

            request = RebuildKVRequest(triggered_by="test")
            response = await trigger_kv_rebuild(request, _=True)

            assert response.status == "submitted"
            assert response.job_method == "sqs"

    @pytest.mark.asyncio
    async def test_thread_fallback_returns_started(self):
        """Should return 'started' status when falling back to thread."""
        with patch("rem.api.routers.admin._submit_sqs_rebuild_job") as mock_sqs:
            mock_sqs.return_value = False

            with patch("rem.api.routers.admin._run_rebuild_in_thread") as mock_thread:
                request = RebuildKVRequest(triggered_by="test")
                response = await trigger_kv_rebuild(request, _=True)

                assert response.status == "started"
                assert response.job_method == "thread"
                mock_thread.assert_called_once()
