from __future__ import annotations

import logging

from sentry.integrations.coding_agent.client import CodingAgentClient
from sentry.integrations.coding_agent.models import CodingAgentLaunchRequest
from sentry.integrations.cursor.models import (
    CursorAgentLaunchRequestBody,
    CursorAgentLaunchRequestPrompt,
    CursorAgentLaunchRequestTarget,
    CursorAgentLaunchRequestWebhook,
    CursorAgentLaunchResponse,
    CursorAgentSource,
    CursorApiKeyMetadata,
)
from sentry.seer.autofix.utils import CodingAgentProviderType, CodingAgentState, CodingAgentStatus
from sentry.seer.models import SeerRepoDefinition

logger = logging.getLogger(__name__)

GITHUB_PROVIDERS = {"github", "integrations:github", "integrations:github_enterprise"}
GITLAB_PROVIDERS = {"integrations:gitlab"}


def _build_repo_url(repo: SeerRepoDefinition) -> str:
    """Build the repository URL based on the provider type.

    GitHub: https://github.com/owner/name
    GitLab: https://{instance}/owner/name (instance parsed from external_id "host:project_id")
    Fallback: GitHub URL for backwards compatibility.
    """
    provider = repo.provider
    if provider in GITLAB_PROVIDERS:
        instance = "gitlab.com"
        if repo.external_id and ":" in repo.external_id:
            instance = repo.external_id.split(":", 1)[0]
        return f"https://{instance}/{repo.owner}/{repo.name}"

    # GitHub and fallback
    return f"https://github.com/{repo.owner}/{repo.name}"


def _is_github_provider(provider: str) -> bool:
    """Return True if the provider is a GitHub variant."""
    return provider in GITHUB_PROVIDERS or provider not in GITLAB_PROVIDERS


class CursorAgentClient(CodingAgentClient):
    integration_name = "cursor"
    base_url = "https://api.cursor.com"
    api_key: str

    def __init__(self, api_key: str, webhook_secret: str):
        super().__init__()
        self.api_key = api_key
        self.webhook_secret = webhook_secret

    def _get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def get_api_key_metadata(self) -> CursorApiKeyMetadata:
        """Fetch metadata about the API key from Cursor's /v0/me endpoint."""
        logger.info(
            "coding_agent.cursor.get_api_key_metadata",
            extra={"agent_type": self.__class__.__name__},
        )

        api_response = self.get(
            "/v0/me",
            headers={
                "content-type": "application/json;charset=utf-8",
                **self._get_auth_headers(),
            },
            timeout=30,
        )

        return CursorApiKeyMetadata.validate(api_response.json)

    def launch(self, webhook_url: str, request: CodingAgentLaunchRequest) -> CodingAgentState:
        """Launch coding agent with webhook callback."""
        repo_url = _build_repo_url(request.repository)
        is_github = _is_github_provider(request.repository.provider)

        payload = CursorAgentLaunchRequestBody(
            prompt=CursorAgentLaunchRequestPrompt(
                text=request.prompt,
            ),
            source=CursorAgentSource(
                repository=repo_url,
                # Use None for empty branch_name so Cursor uses repo's default branch
                ref=request.repository.branch_name or None,
            ),
            webhook=CursorAgentLaunchRequestWebhook(url=webhook_url, secret=self.webhook_secret),
            target=CursorAgentLaunchRequestTarget(
                autoCreatePr=request.auto_create_pr,
                branchName=request.branch_name,
                openAsCursorGithubApp=is_github,
            ),
        )

        logger.info(
            "coding_agent.cursor.launch",
            extra={
                "webhook_url": webhook_url,
                "agent_type": self.__class__.__name__,
            },
        )

        # Use shared ApiClient to get consistent error handling with body surfaced
        api_response = self.post(
            "/v0/agents",
            headers={
                "content-type": "application/json;charset=utf-8",
                **self._get_auth_headers(),
            },
            data=payload.dict(exclude_none=True),
            json=True,
            timeout=60,
        )

        launch_response = CursorAgentLaunchResponse.validate(api_response.json)

        return CodingAgentState(
            id=launch_response.id,
            status=CodingAgentStatus.RUNNING,  # Cursor agent doesn't send when it actually starts so we just assume it's running
            provider=CodingAgentProviderType.CURSOR_BACKGROUND_AGENT,
            name=f"{request.repository.owner}/{request.repository.name}: {launch_response.name or f'Cursor Agent {launch_response.id}'}",
            started_at=launch_response.createdAt,
            agent_url=launch_response.target.url,
        )
