# ============================================================
# Yuno Agent Platform — Database Seed
#
# Seeds the database with:
# 1. Pre-built agents (Research, Analysis, Report, etc.)
# 2. Workflow templates (Research Team, Content Team)
#
# Idempotent — safe to run multiple times.
# Called during application startup.
# ============================================================
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionFactory
from app.logger import get_logger
from app.models import Agent, Workflow

logger = get_logger(__name__)


RESEARCH_AGENTS = [
    {
        "name": "Research Agent",
        "role": "researcher",
        "system_prompt": (
            "You are an expert research agent with deep knowledge across multiple domains. "
            "Your task is to gather comprehensive, accurate information on the given topic. "
            "Structure your research with clear sections: Key Facts, Recent Developments, "
            "Important Context, and Data Points. Be thorough but concise. "
            "Always cite your reasoning and flag any uncertainties."
        ),
        "model": "gpt-4o-mini",
        "tools": ["web_search"],
        "memory_settings": {"type": "buffer", "window": 10},
        "channels": ["web", "telegram"],
        "guardrails": {"max_iterations": 5, "timeout_seconds": 60},
    },
    {
        "name": "Analysis Agent",
        "role": "analyst",
        "system_prompt": (
            "You are a senior analysis agent specializing in synthesizing research into actionable insights. "
            "You receive research data and produce structured analysis covering: "
            "1) Key Findings, 2) Patterns and Trends, 3) Implications, 4) Confidence Assessment. "
            "Be analytical, objective, and highlight both opportunities and risks. "
            "Your output feeds directly into the final report."
        ),
        "model": "gpt-4o-mini",
        "tools": ["calculator"],
        "memory_settings": {"type": "buffer", "window": 10},
        "channels": ["web"],
        "guardrails": {"max_iterations": 3, "timeout_seconds": 60},
    },
    {
        "name": "Report Agent",
        "role": "reporter",
        "system_prompt": (
            "You are an expert report writer who transforms research and analysis into "
            "polished, professional documents. Given research findings and analysis, produce "
            "a comprehensive report with: Executive Summary, Detailed Findings, Analysis, "
            "Recommendations, and Next Steps. Write clearly for both technical and non-technical audiences. "
            "Format using markdown with proper headers and bullet points."
        ),
        "model": "gpt-4o-mini",
        "tools": [],
        "memory_settings": {"type": "buffer", "window": 10},
        "channels": ["web", "telegram"],
        "guardrails": {"max_iterations": 3, "timeout_seconds": 90},
    },
]

CONTENT_AGENTS = [
    {
        "name": "Idea Agent",
        "role": "ideator",
        "system_prompt": (
            "You are a creative ideation agent specializing in content strategy. "
            "Given a topic or brief, generate 5 compelling content ideas with: "
            "Title, Angle, Target Audience, Key Message, and Estimated Impact. "
            "Think creatively, consider multiple formats (blog, video, social, newsletter), "
            "and prioritize ideas that are original, timely, and valuable to the audience."
        ),
        "model": "gpt-4o-mini",
        "tools": [],
        "memory_settings": {"type": "buffer", "window": 10},
        "channels": ["web"],
        "guardrails": {"max_iterations": 3, "timeout_seconds": 60},
    },
    {
        "name": "Writer Agent",
        "role": "writer",
        "system_prompt": (
            "You are a professional content writer who creates engaging, high-quality content. "
            "Given an approved idea from the Idea Agent, write complete, polished content. "
            "Follow best practices for the content type (blog: SEO + headers, social: concise + hooks). "
            "Write with a clear voice, strong opening, supporting evidence, and compelling conclusion. "
            "Target 600-1000 words for articles, 150-280 for social posts."
        ),
        "model": "gpt-4o-mini",
        "tools": [],
        "memory_settings": {"type": "buffer", "window": 10},
        "channels": ["web"],
        "guardrails": {"max_iterations": 3, "timeout_seconds": 90},
    },
    {
        "name": "Reviewer Agent",
        "role": "reviewer",
        "system_prompt": (
            "You are a senior content editor who ensures quality and consistency. "
            "Review the written content and provide: 1) Revised Content (improved version), "
            "2) Changes Made (list of improvements), 3) Quality Score (1-10), "
            "4) Publication Recommendation. Fix grammar, improve clarity, strengthen arguments, "
            "and ensure the content achieves its stated goal. Be constructive and specific."
        ),
        "model": "gpt-4o-mini",
        "tools": [],
        "memory_settings": {"type": "buffer", "window": 10},
        "channels": ["web"],
        "guardrails": {"max_iterations": 3, "timeout_seconds": 60},
    },
]


def build_research_team_workflow(agent_ids: dict[str, str]) -> dict:
    """
    Build the Research Team workflow graph.

    Flow: Trigger → Research Agent → Analysis Agent → Report Agent

    Nodes use React Flow format so they render correctly in the visual builder.
    """
    return {
        "nodes": [
            {
                "id": "trigger-1",
                "type": "triggerNode",
                "position": {"x": 100, "y": 200},
                "data": {
                    "label": "User Input",
                    "node_type": "trigger",
                    "config": {},
                },
            },
            {
                "id": "research-1",
                "type": "agentNode",
                "position": {"x": 350, "y": 200},
                "data": {
                    "label": "Research Agent",
                    "node_type": "agent",
                    "agent_id": agent_ids.get("Research Agent", ""),
                    "config": {"role": "researcher"},
                },
            },
            {
                "id": "analysis-1",
                "type": "agentNode",
                "position": {"x": 600, "y": 200},
                "data": {
                    "label": "Analysis Agent",
                    "node_type": "agent",
                    "agent_id": agent_ids.get("Analysis Agent", ""),
                    "config": {"role": "analyst"},
                },
            },
            {
                "id": "report-1",
                "type": "agentNode",
                "position": {"x": 850, "y": 200},
                "data": {
                    "label": "Report Agent",
                    "node_type": "agent",
                    "agent_id": agent_ids.get("Report Agent", ""),
                    "config": {"role": "reporter"},
                },
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "trigger-1",
                "target": "research-1",
                "label": "input",
            },
            {
                "id": "e2",
                "source": "research-1",
                "target": "analysis-1",
                "label": "research data",
            },
            {
                "id": "e3",
                "source": "analysis-1",
                "target": "report-1",
                "label": "analysis",
            },
        ],
    }


def build_content_team_workflow(agent_ids: dict[str, str]) -> dict:
    """
    Build the Content Team workflow graph.

    Flow: Trigger → Idea Agent → Writer Agent → Reviewer Agent
    """
    return {
        "nodes": [
            {
                "id": "trigger-1",
                "type": "triggerNode",
                "position": {"x": 100, "y": 200},
                "data": {
                    "label": "Content Brief",
                    "node_type": "trigger",
                    "config": {},
                },
            },
            {
                "id": "idea-1",
                "type": "agentNode",
                "position": {"x": 350, "y": 200},
                "data": {
                    "label": "Idea Agent",
                    "node_type": "agent",
                    "agent_id": agent_ids.get("Idea Agent", ""),
                    "config": {"role": "ideator"},
                },
            },
            {
                "id": "writer-1",
                "type": "agentNode",
                "position": {"x": 600, "y": 200},
                "data": {
                    "label": "Writer Agent",
                    "node_type": "agent",
                    "agent_id": agent_ids.get("Writer Agent", ""),
                    "config": {"role": "writer"},
                },
            },
            {
                "id": "reviewer-1",
                "type": "agentNode",
                "position": {"x": 850, "y": 200},
                "data": {
                    "label": "Reviewer Agent",
                    "node_type": "agent",
                    "agent_id": agent_ids.get("Reviewer Agent", ""),
                    "config": {"role": "reviewer"},
                },
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "trigger-1",
                "target": "idea-1",
                "label": "brief",
            },
            {
                "id": "e2",
                "source": "idea-1",
                "target": "writer-1",
                "label": "best idea",
            },
            {
                "id": "e3",
                "source": "writer-1",
                "target": "reviewer-1",
                "label": "draft",
            },
        ],
    }


async def seed_templates() -> None:
    """
    Seed database with agents and workflow templates.
    Idempotent: checks by name before inserting.
    """
    async with AsyncSessionFactory() as session:
        # ---- Seed Agents ----------------------------------------
        agent_ids: dict[str, str] = {}
        all_agent_configs = RESEARCH_AGENTS + CONTENT_AGENTS

        for config in all_agent_configs:
            # Check if agent already exists
            result = await session.execute(
                select(Agent).where(Agent.name == config["name"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                agent_ids[existing.name] = existing.id
                continue

            agent = Agent(**config)
            session.add(agent)
            await session.flush()  # Get the ID without committing
            agent_ids[agent.name] = agent.id
            logger.info("agent_seeded", name=agent.name)

        await session.commit()

        # ---- Seed Research Team Template -------------------------
        result = await session.execute(
            select(Workflow).where(Workflow.name == "Research Team")
        )
        if not result.scalar_one_or_none():
            graph = build_research_team_workflow(agent_ids)
            workflow = Workflow(
                name="Research Team",
                description=(
                    "Multi-agent research pipeline: Research Agent gathers data, "
                    "Analysis Agent synthesizes insights, Report Agent produces final document."
                ),
                nodes=graph["nodes"],
                edges=graph["edges"],
                is_template=True,
                template_type="research",
            )
            session.add(workflow)
            logger.info("template_seeded", name="Research Team")

        # ---- Seed Content Team Template --------------------------
        result = await session.execute(
            select(Workflow).where(Workflow.name == "Content Team")
        )
        if not result.scalar_one_or_none():
            graph = build_content_team_workflow(agent_ids)
            workflow = Workflow(
                name="Content Team",
                description=(
                    "Multi-agent content creation: Idea Agent generates concepts, "
                    "Writer Agent drafts content, Reviewer Agent edits and scores."
                ),
                nodes=graph["nodes"],
                edges=graph["edges"],
                is_template=True,
                template_type="content",
            )
            session.add(workflow)
            logger.info("template_seeded", name="Content Team")

        await session.commit()
        logger.info("seed_complete", agent_count=len(agent_ids))
