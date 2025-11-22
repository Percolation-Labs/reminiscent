# API Design Discussion - RESTful vs GraphQL

**Date**: 2025-01-15 09:00 AM
**Participants**: Sarah Chen (Tech Lead), Mike Rodriguez (Backend), Alice Wong (Frontend)
**Duration**: 45 minutes

## Context
Team discussed architectural approach for the new customer API. Current REST endpoints are becoming unwieldy with 20+ endpoints and multiple roundtrips for complex data.

## Key Points Discussed

### GraphQL Proposal (Mike)
- Single endpoint `/graphql`
- Client specifies exact data needs
- Reduces over-fetching
- Built-in introspection and type safety
- Concern: Learning curve for team

### REST Alternative (Sarah)
- Stick with familiar patterns
- Add compound endpoints for common use cases
- Use JSON:API specification for consistency
- Concern: Proliferation of endpoints

### Frontend Perspective (Alice)
- Mobile app needs efficient data fetching
- Current approach requires 4-5 API calls per screen
- TypeScript integration is critical
- GraphQL codegen looks promising

## Decision
Moving forward with GraphQL POC for customer-facing API. Will use Apollo Server on backend, Apollo Client on frontend. Timeline: 2 week spike.

## Action Items
- Mike: Set up Apollo Server boilerplate
- Alice: Evaluate Apollo Client vs urql
- Sarah: Document migration strategy for existing endpoints

## References
- Compared to Netflix API evolution (REST → GraphQL)
- Discussed Shopify's public GraphQL API as reference
- Referenced internal database schema for Customer domain
