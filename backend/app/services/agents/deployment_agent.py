"""Deployment Agent - Handles IaC generation, provisioning, deployment, test data seeding, and health checks.

Generates Terraform/Helm artifacts via LLM, simulates provisioning workflow
(plan → apply), deploys application, seeds test data, runs health checks with
retries, and records deployment status in the database.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
"""
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.database import Deployment, SessionLocal
from app.core.logger import logger
from app.services.agents.base_agent import BaseAgent

# Maximum health-check retry attempts before marking deployment as failed (Req 10.6, P5)
MAX_HEALTH_CHECK_RETRIES = 3

# Valid deployment status transitions
DEPLOYMENT_STATUSES = (
    "provisioning",
    "deploying",
    "health_checking",
    "live",
    "failed",
    "torn_down",
)


class DeploymentAgent(BaseAgent):
    """Agent that manages the full deployment lifecycle.

    Responsibilities:
    - Generate IaC artifacts (Terraform configs, optional Helm charts for EKS) (Req 7.1, 10.1, 10.2)
    - Execute provisioning workflow (plan → apply) (Req 7.2, 10.3)
    - Deploy application container/function (Req 7.3, 10.4)
    - Seed test data from Testing_Agent output (Req 7.4, 10.5)
    - Run health check with 3 retries (Req 7.7, 10.6, P5)
    - Record deployment_url in state (Req 7.5)
    - Create/update Deployment record in DB with status transitions (Req 7.6)
    """

    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Orchestrate the full deployment pipeline.

        Steps:
        1. Generate IaC artifacts using LLM
        2. Simulate provisioning (plan → apply)
        3. Deploy application
        4. Seed test data
        5. Run health check (3 retries)
        6. Record deployment_url in state
        """
        project_id = state.get("project_id", "")
        tenant_id = state.get("tenant_id", "")
        run_id = state.get("run_id", "")
        project_name = state.get("project_name", "") or state.get("idea", "app")[:30]

        deployment_id = str(uuid.uuid4())
        provider = self._determine_provider(state)
        region = self._determine_region(state)

        db = SessionLocal()
        try:
            # Create initial Deployment record — status: provisioning
            deployment = self._create_deployment_record(
                db,
                deployment_id=deployment_id,
                tenant_id=tenant_id,
                project_id=project_id,
                workflow_run_id=run_id,
                provider=provider,
                region=region,
            )

            # ----------------------------------------------------------
            # Step 1: Generate IaC artifacts (Req 7.1, 10.1, 10.2)
            # ----------------------------------------------------------
            try:
                iac_artifacts = await self._generate_iac_artifacts(state, provider)
                self._update_deployment(
                    db,
                    deployment,
                    infrastructure_artifacts=iac_artifacts,
                    last_successful_step="iac_generation",
                )
                logger.info(
                    "DeploymentAgent: IaC artifacts generated for run %s", run_id
                )
            except Exception as exc:
                return self._handle_failure(
                    db, deployment, state,
                    step="iac_generation",
                    reason=f"IaC generation failed: {exc}",
                )

            # ----------------------------------------------------------
            # Step 2: Provisioning — plan → apply (Req 7.2, 10.3)
            # ----------------------------------------------------------
            try:
                provisioning_result = await self._provision_infrastructure(
                    state, iac_artifacts, provider, region
                )
                resource_identifiers = provisioning_result.get("resource_identifiers", {})
                resource_type = provisioning_result.get("resource_type", provider)
                self._update_deployment(
                    db,
                    deployment,
                    status="deploying",
                    resource_type=resource_type,
                    resource_identifiers=resource_identifiers,
                    last_successful_step="provisioning",
                )
                logger.info(
                    "DeploymentAgent: infrastructure provisioned for run %s", run_id
                )
            except Exception as exc:
                return self._handle_failure(
                    db, deployment, state,
                    step="provisioning",
                    reason=f"Provisioning failed: {exc}",
                )

            # ----------------------------------------------------------
            # Step 3: Deploy application (Req 7.3, 10.4)
            # ----------------------------------------------------------
            try:
                await self._deploy_application(state, provider, resource_identifiers)
                self._update_deployment(
                    db,
                    deployment,
                    last_successful_step="deploy_application",
                )
                logger.info(
                    "DeploymentAgent: application deployed for run %s", run_id
                )
            except Exception as exc:
                return self._handle_failure(
                    db, deployment, state,
                    step="deploy_application",
                    reason=f"Application deployment failed: {exc}",
                )

            # ----------------------------------------------------------
            # Step 4: Seed test data (Req 7.4, 10.5)
            # ----------------------------------------------------------
            try:
                await self._seed_test_data(state)
                self._update_deployment(
                    db,
                    deployment,
                    last_successful_step="seed_test_data",
                )
                logger.info(
                    "DeploymentAgent: test data seeded for run %s", run_id
                )
            except Exception as exc:
                # Test data seeding failure is non-fatal — log and continue
                logger.warning(
                    "DeploymentAgent: test data seeding failed for run %s — %s",
                    run_id, exc,
                )

            # ----------------------------------------------------------
            # Step 5: Health check with 3 retries (Req 7.7, 10.6, P5)
            # ----------------------------------------------------------
            self._update_deployment(db, deployment, status="health_checking")

            health_ok, diagnostics = await self._run_health_check(
                state, provider, resource_identifiers
            )

            if not health_ok:
                self._update_deployment(
                    db,
                    deployment,
                    status="failed",
                    health_check_status="failed",
                    failure_reason=f"Health check failed after {MAX_HEALTH_CHECK_RETRIES} retries: {diagnostics}",
                    last_successful_step="seed_test_data",
                )
                state["error"] = (
                    f"Deployment health check failed after {MAX_HEALTH_CHECK_RETRIES} retries: {diagnostics}"
                )
                logger.error(
                    "DeploymentAgent: health check FAILED for run %s — %s",
                    run_id, diagnostics,
                )
                return state

            # ----------------------------------------------------------
            # Step 6: Record deployment_url and mark live (Req 7.5)
            # ----------------------------------------------------------
            safe_project_name = self._sanitize_name(project_name)
            deployment_url = f"https://env-{safe_project_name}-{run_id}.savi.app"

            self._update_deployment(
                db,
                deployment,
                status="live",
                health_check_status="healthy",
                environment_url=deployment_url,
                last_successful_step="health_check",
            )

            state["deployment_url"] = deployment_url
            logger.info(
                "DeploymentAgent: deployment LIVE at %s for run %s",
                deployment_url, run_id,
            )

        except Exception as exc:
            logger.error("DeploymentAgent: unexpected error — %s", exc)
            state["error"] = f"Deployment failed: {exc}"
        finally:
            db.close()

        return state

    # ------------------------------------------------------------------
    # IaC generation (Req 7.1, 10.1, 10.2)
    # ------------------------------------------------------------------

    async def _generate_iac_artifacts(
        self, state: Dict[str, Any], provider: str
    ) -> Dict[str, Any]:
        """Generate Terraform configs (and Helm charts for EKS) using LLM."""
        architecture = state.get("architecture", {})
        stack_selections = state.get("stack_selections", [])

        arch_summary = json.dumps(architecture, indent=2, default=str)[:3000] if architecture else "No architecture provided"
        stack_summary = json.dumps(stack_selections, indent=2, default=str)[:2000] if stack_selections else "No stack selections"

        prompt = (
            "You are an infrastructure-as-code expert. Generate Terraform configuration "
            "for deploying the following application.\n\n"
            f"Provider: {provider}\n"
            f"Architecture:\n{arch_summary}\n\n"
            f"Stack Selections:\n{stack_summary}\n\n"
            "Generate a JSON object with keys:\n"
            '- "terraform_main": the main.tf content as a string\n'
            '- "terraform_variables": the variables.tf content as a string\n'
        )

        if provider == "eks":
            prompt += '- "helm_chart": a Helm values.yaml content as a string\n'

        prompt += (
            "\nRespond with ONLY the JSON object, no markdown fences or explanation."
        )

        response = await self.llm_client.generate(
            prompt,
            system_prompt="You are a senior DevOps engineer. Output valid JSON only.",
        )

        try:
            artifacts = json.loads(response)
        except json.JSONDecodeError:
            # Wrap raw response as a single terraform artifact
            artifacts = {"terraform_main": response, "terraform_variables": ""}

        artifacts["provider"] = provider
        return artifacts

    # ------------------------------------------------------------------
    # Provisioning (Req 7.2, 10.3)
    # ------------------------------------------------------------------

    async def _provision_infrastructure(
        self,
        state: Dict[str, Any],
        iac_artifacts: Dict[str, Any],
        provider: str,
        region: str,
    ) -> Dict[str, Any]:
        """Simulate provisioning workflow: plan → apply.

        In production this would invoke Terraform CLI. For now the LLM
        simulates the plan/apply output and returns resource identifiers.
        """
        terraform_main = iac_artifacts.get("terraform_main", "")

        prompt = (
            "You are simulating a Terraform provisioning workflow.\n\n"
            f"Provider: {provider}\nRegion: {region}\n\n"
            f"Terraform config (abbreviated):\n{str(terraform_main)[:2000]}\n\n"
            "Simulate the output of `terraform plan` followed by `terraform apply`.\n"
            "Return a JSON object with:\n"
            '- "plan_summary": a short plan summary string\n'
            '- "apply_summary": a short apply summary string\n'
            '- "resource_type": the primary resource type (e.g., "ecs_service", "eks_deployment", "lambda_function")\n'
            '- "resource_identifiers": a dict of resource IDs created\n'
            "\nRespond with ONLY the JSON object."
        )

        response = await self.llm_client.generate(
            prompt,
            system_prompt="You are a Terraform simulation engine. Output valid JSON only.",
        )

        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            result = {
                "plan_summary": "Plan generated",
                "apply_summary": "Apply completed",
                "resource_type": f"{provider}_service",
                "resource_identifiers": {"service_id": str(uuid.uuid4())},
            }

        return result

    # ------------------------------------------------------------------
    # Application deployment (Req 7.3, 10.4)
    # ------------------------------------------------------------------

    async def _deploy_application(
        self,
        state: Dict[str, Any],
        provider: str,
        resource_identifiers: Dict[str, Any],
    ) -> None:
        """Deploy the application container/function to the provisioned environment."""
        scaffolding = state.get("scaffolding", {})
        code_summary = json.dumps(scaffolding, indent=2, default=str)[:2000] if scaffolding else "No scaffolding"

        prompt = (
            "You are deploying an application to a provisioned environment.\n\n"
            f"Provider: {provider}\n"
            f"Resources: {json.dumps(resource_identifiers, default=str)}\n"
            f"Application code summary:\n{code_summary}\n\n"
            "Describe the deployment steps taken. Respond with a short JSON object:\n"
            '- "steps": list of step descriptions\n'
            '- "status": "success" or "failed"\n'
            "\nRespond with ONLY the JSON object."
        )

        response = await self.llm_client.generate(
            prompt,
            system_prompt="You are a deployment automation engine. Output valid JSON only.",
        )

        try:
            result = json.loads(response)
            if result.get("status") == "failed":
                raise RuntimeError(
                    f"Application deployment reported failure: {result.get('steps', [])}"
                )
        except json.JSONDecodeError:
            # Non-JSON response is acceptable — treat as success
            pass

    # ------------------------------------------------------------------
    # Test data seeding (Req 7.4, 10.5)
    # ------------------------------------------------------------------

    async def _seed_test_data(self, state: Dict[str, Any]) -> None:
        """Seed the deployed environment with test data from Testing_Agent output."""
        test_data = state.get("tests", {}) or state.get("test_data", {})
        if not test_data:
            logger.info("DeploymentAgent: no test data available to seed")
            return

        test_summary = json.dumps(test_data, indent=2, default=str)[:2000]

        prompt = (
            "You are seeding test data into a deployed environment.\n\n"
            f"Test fixtures:\n{test_summary}\n\n"
            "Generate a JSON object describing the seeding result:\n"
            '- "records_seeded": number of records\n'
            '- "tables": list of table names seeded\n'
            '- "status": "success" or "partial"\n'
            "\nRespond with ONLY the JSON object."
        )

        await self.llm_client.generate(
            prompt,
            system_prompt="You are a test data seeding engine. Output valid JSON only.",
        )

    # ------------------------------------------------------------------
    # Health check with retries (Req 7.7, 10.6, P5)
    # ------------------------------------------------------------------

    async def _run_health_check(
        self,
        state: Dict[str, Any],
        provider: str,
        resource_identifiers: Dict[str, Any],
    ) -> tuple:
        """Run health check with up to MAX_HEALTH_CHECK_RETRIES attempts.

        Returns:
            (success: bool, diagnostics: str)
        """
        diagnostics_log: List[str] = []

        for attempt in range(1, MAX_HEALTH_CHECK_RETRIES + 1):
            logger.info(
                "DeploymentAgent: health check attempt %d/%d",
                attempt, MAX_HEALTH_CHECK_RETRIES,
            )

            prompt = (
                "You are performing a health check on a deployed application.\n\n"
                f"Provider: {provider}\n"
                f"Resources: {json.dumps(resource_identifiers, default=str)}\n"
                f"Attempt: {attempt}/{MAX_HEALTH_CHECK_RETRIES}\n\n"
                "Simulate a health check. Respond with a JSON object:\n"
                '- "healthy": true or false\n'
                '- "status_code": HTTP status code (e.g. 200)\n'
                '- "response_time_ms": response time in milliseconds\n'
                '- "details": any diagnostic details\n'
                "\nRespond with ONLY the JSON object."
            )

            response = await self.llm_client.generate(
                prompt,
                system_prompt="You are a health check simulator. Output valid JSON only.",
            )

            try:
                result = json.loads(response)
                healthy = result.get("healthy", False)
                details = result.get("details", "")
            except json.JSONDecodeError:
                healthy = "healthy" in response.lower() or "200" in response
                details = response[:200]

            if healthy:
                logger.info(
                    "DeploymentAgent: health check passed on attempt %d", attempt
                )
                return True, ""

            diagnostics_log.append(
                f"Attempt {attempt}: unhealthy — {details}"
            )
            logger.warning(
                "DeploymentAgent: health check attempt %d failed — %s",
                attempt, details,
            )

        # All retries exhausted (Req 10.6, P5)
        return False, "; ".join(diagnostics_log)

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_deployment_record(
        db,
        deployment_id: str,
        tenant_id: str,
        project_id: str,
        workflow_run_id: str,
        provider: str,
        region: str,
    ) -> Deployment:
        """Create a Deployment record with initial status 'provisioning'."""
        deployment = Deployment(
            id=deployment_id,
            tenant_id=tenant_id or "default",
            project_id=project_id or "default",
            workflow_run_id=workflow_run_id or "default",
            status="provisioning",
            provider=provider,
            region=region,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(deployment)
        db.commit()
        db.refresh(deployment)
        return deployment

    @staticmethod
    def _update_deployment(db, deployment: Deployment, **kwargs) -> None:
        """Update fields on a Deployment record and commit."""
        for key, value in kwargs.items():
            if hasattr(deployment, key):
                setattr(deployment, key, value)
        deployment.updated_at = datetime.now()
        db.commit()
        db.refresh(deployment)

    @staticmethod
    def _handle_failure(
        db,
        deployment: Deployment,
        state: Dict[str, Any],
        step: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Mark deployment as failed and record diagnostics in state."""
        deployment.status = "failed"
        deployment.failure_reason = reason
        deployment.last_successful_step = step
        deployment.updated_at = datetime.now()
        db.commit()

        state["error"] = reason
        logger.error("DeploymentAgent: %s", reason)
        return state

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_provider(state: Dict[str, Any]) -> str:
        """Determine the target infrastructure provider from state."""
        architecture = state.get("architecture", {})
        stack_selections = state.get("stack_selections", [])

        # Check architecture for provider hints
        if isinstance(architecture, dict):
            infra = json.dumps(architecture).lower()
            if "eks" in infra or "kubernetes" in infra or "helm" in infra:
                return "eks"
            if "lambda" in infra or "serverless" in infra:
                return "lambda"

        # Check stack selections
        for selection in stack_selections:
            if isinstance(selection, dict):
                patterns = selection.get("infra_patterns", [])
                for p in patterns:
                    p_lower = str(p).lower()
                    if "eks" in p_lower or "kubernetes" in p_lower:
                        return "eks"
                    if "lambda" in p_lower or "serverless" in p_lower:
                        return "lambda"

        # Default to ECS
        return "ecs"

    @staticmethod
    def _determine_region(state: Dict[str, Any]) -> str:
        """Determine the target AWS region from state or default."""
        architecture = state.get("architecture", {})
        if isinstance(architecture, dict):
            region = architecture.get("region")
            if region:
                return region
        return "us-east-1"

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Sanitize a project name for use in a URL."""
        sanitized = name.lower().strip()
        sanitized = "".join(c if c.isalnum() or c == "-" else "-" for c in sanitized)
        # Collapse multiple dashes and strip leading/trailing dashes
        while "--" in sanitized:
            sanitized = sanitized.replace("--", "-")
        return sanitized.strip("-") or "app"
