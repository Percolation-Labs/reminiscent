# Daily Standup - January 16, 2025

**Time**: 9:30 AM
**Attendees**: Sarah, Mike, Alice, Jordan (PM), Lisa (QA)

## Updates

### Sarah
**Yesterday**:
- Reviewed GraphQL POC with architecture team
- Finalized TiDB migration plan
- 1:1 with Mike about API design concerns

**Today**:
- Present TiDB plan to leadership
- Code review for authentication service
- Start GraphQL schema design

**Blockers**: None

### Mike
**Yesterday**:
- Set up Apollo Server boilerplate
- Experimented with schema stitching
- Fixed bug in user service (CVE-2024-1234)

**Today**:
- Define GraphQL schema for Customer domain
- Add authentication middleware
- Pair with Alice on client integration

**Blockers**: Waiting for schema feedback from Sarah

### Alice
**Yesterday**:
- Evaluated Apollo Client vs urql
- Prototyped mobile app data flow
- Fixed TypeScript build issues

**Today**:
- Integrate Apollo Client in React Native app
- Set up codegen for TypeScript types
- Write integration tests

**Blockers**: None

### Jordan (PM)
**Yesterday**:
- Customer interviews for new dashboard
- Roadmap sync with Product VP
- Reviewed Q1 metrics

**Today**:
- Prioritize GraphQL feature set
- Update Jira epics
- Stakeholder meeting at 2 PM

**Blockers**: Need engineering estimates for Q2 planning

### Lisa (QA)
**Yesterday**:
- Automated tests for payment flow
- Performance testing on staging
- Bug triage (12 new issues)

**Today**:
- GraphQL testing strategy
- Regression testing for hotfix
- Load test TiDB POC

**Blockers**: Staging environment down (DevOps working on it)

## Key Discussion Points

### GraphQL Schema Design
- Mike and Sarah to collaborate on schema this week
- Use federation approach for multiple services
- Document breaking change policy

### TiDB Migration
- Leadership buy-in needed before Phase 1
- Sarah presenting cost-benefit analysis today
- DevOps to allocate EKS capacity

### Staging Environment
- Lisa flagged issue - DevOps investigating
- Temporary workaround: use local docker-compose
- Expected resolution: today EOD

## Action Items
- Sarah: Present TiDB plan to leadership [Today 2 PM]
- Mike: Share draft GraphQL schema [Tomorrow]
- Alice: Document Apollo Client decision [End of week]
- Jordan: Send Q2 planning timeline [Today]
- Lisa: Create GraphQL testing plan [Friday]
