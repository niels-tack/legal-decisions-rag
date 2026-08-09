# Technical requirements: legal-decisions-rag

> **Single source of truth for technical architecture and constraints**
> 
> This document defines how the project should be built. Update this as technical decisions are made.
> AI coding assistants will reference this to ensure code follows the right patterns and constraints.

## Technical preferences

**Language**: Python 3.13

**Package Manager**: uv

**Code Quality**:
- Linting: Ruff
- Type Checking: Ty
- Testing: pytest

## Engineering context

> Fill out this document to seed the project initialization workflow.
> Replace `[placeholders]` with your information. Delete sections that don't apply.

## Technical preferences (additional)

**Language**: [e.g., Python 3.12+]

**Web Framework**: [e.g., FastAPI, Django, or "no preference"]

**Database**: [e.g., PostgreSQL, SQLite for dev, or "no preference"]

**Other Preferences**:
- [e.g., "Prefer async over sync"]
- [e.g., "Use Pydantic for validation"]
- [e.g., "Prefer composition over inheritance"]

## Existing systems

[Any systems this must integrate with?]

**APIs**: [External APIs to consume or expose]

**Databases**: [Existing databases to connect to]

**Services**: [Other services in the ecosystem]

**Authentication**: [Existing auth system to integrate with, or "standalone"]

## Architecture ideas

[Any initial thoughts on structure? Even rough ideas help.]

**Patterns to Consider**:
- [e.g., "Event-driven for notifications"]
- [e.g., "Repository pattern for data access"]
- [e.g., "Microservices vs. monolith: prefer monolith initially"]

**Patterns to Avoid**:
- [e.g., "No complex ORM magic"]
- [e.g., "Avoid premature optimization"]

## Technical constraints

**Deployment Target**: [e.g., GCP Cloud Run, AWS Lambda, local Docker, Kubernetes]

**Scaling Requirements**:
- Expected users: [number or range]
- Expected data volume: [size estimates]
- Peak load expectations: [if known]

**Security Requirements**:
- [e.g., "Data encryption at rest"]
- [e.g., "SOC2 compliance required"]
- [e.g., "No PII storage"]

## Non-Functional Requirements

**Performance**:
- Response time: [e.g., "< 200ms for API calls"]
- Throughput: [e.g., "100 requests/second"]

**Availability**:
- Uptime target: [e.g., "99.9%"]
- Acceptable downtime: [e.g., "Maintenance windows OK"]

**Observability**:
- Logging: [requirements]
- Monitoring: [requirements]
- Alerting: [requirements]

## Team Context

**Team Size**: [Solo / Small team / Large team]

**Skill Levels**: [Junior / Mixed / Senior]

**Maintenance Plan**: [Who maintains this long-term?]

## Dependencies & Risks

**External Dependencies**:
- [e.g., "Requires OpenAI API access"]
- [e.g., "Depends on internal auth service"]

**Known Risks**:
- [e.g., "API rate limits may affect throughput"]
- [e.g., "Third-party service reliability unknown"]

## Open Technical Questions

[Technical uncertainties needing research]

- [Question 1: e.g., "Best approach for real-time updates?"]
- [Question 2: e.g., "How to handle large file uploads?"]
