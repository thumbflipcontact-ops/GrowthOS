"""Import every model module so SQLAlchemy's declarative registry sees the full schema —
required for relationship() string resolution and for Alembic's autogenerate diffing.
"""

from app.models.agent import AgentConfig, AgentRun, AgentRunStatus
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.billing import Subscription, SubscriptionStatus
from app.models.brief import DailyBrief
from app.models.content import ContentItem, ContentItemStatus
from app.models.crm import Company, Competitor, CompetitorObservation, Contact, ContactStatus
from app.models.event import DomainEvent
from app.models.identity import Membership, MembershipRole, Organization, User
from app.models.knowledge import BuyingIntent, KnowledgeItem
from app.models.plugin import (
    PluginCapability,
    PluginCatalogEntry,
    PluginConnection,
    PluginConnectionStatus,
)
from app.models.project import Project, ProjectStatus

__all__ = [
    "AgentConfig",
    "AgentRun",
    "AgentRunStatus",
    "AuditLog",
    "Base",
    "DailyBrief",
    "ContentItem",
    "ContentItemStatus",
    "Company",
    "Competitor",
    "CompetitorObservation",
    "Contact",
    "ContactStatus",
    "DomainEvent",
    "Membership",
    "MembershipRole",
    "Organization",
    "User",
    "BuyingIntent",
    "KnowledgeItem",
    "PluginCapability",
    "PluginCatalogEntry",
    "PluginConnection",
    "PluginConnectionStatus",
    "Project",
    "ProjectStatus",
    "Subscription",
    "SubscriptionStatus",
]
