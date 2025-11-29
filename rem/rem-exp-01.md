# REM Database Exploration - Experiment 01

Data modeling exercise exploring the mental health / psychotropic drug database.
All queries verified with actual results from the production cluster.

## Database Summary

| Table | Count | Description |
|-------|-------|-------------|
| `resources` | 843 | Drugs, care stages, roles, treatment guides, crisis resources |
| `users` | 4 | User profiles (Sarah Chen, Mike Johnson, Alex Kim) |
| `moments` | 4 | Temporal events (meetings, coding sessions) |
| `messages` | 53 | Chat messages |
| `embeddings_resources` | 843 | Vector embeddings for semantic search |

### Resource Categories

| Category | Count |
|----------|-------|
| `treatment-guide` | 595 |
| `crisis` | 96 |
| `drug.psychotropic` | 41 |
| `drug.psychotropic.antipsychotic` | 22 |
| `drug.psychotropic.anxiolytic` | 14 |
| `drug.psychotropic.ssri` | 8 |
| `care.role` | 8 |
| `care.stage` | 7 |
| `patient-education` | 7 |
| `care-model` | 6 |
| `drug.psychotropic.mood_stabilizer` | 6 |
| `drug.psychotropic.snri` | 5 |

---

## Batch 1: LOOKUP Queries (10 queries)

Exact match O(1) lookups on entity labels.

### 1.1 Lookup a specific SSRI medication
```sql
-- LOOKUP "Sertraline"
SELECT name, category FROM resources WHERE name = 'Sertraline';
```
**Result:** 2 rows (ssri, drug.psychotropic.ssri)

### 1.2 Lookup a care stage
```sql
-- LOOKUP "Active Treatment"
SELECT name, category FROM resources WHERE name = 'Active Treatment';
```
**Result:** 1 row (care.stage)

### 1.3 Lookup a care role
```sql
-- LOOKUP "Psychiatrist"
SELECT name, category FROM resources WHERE name = 'Psychiatrist';
```
**Result:** 1 row (care.role)

### 1.4 Lookup an antipsychotic
```sql
-- LOOKUP "Brexpiprazole"
SELECT name, category FROM resources WHERE name = 'Brexpiprazole';
```
**Result:** 1 row (drug.psychotropic.antipsychotic)

### 1.5 Lookup a user
```sql
-- LOOKUP "Sarah Chen" FROM users
SELECT name, email FROM users WHERE name = 'Sarah Chen';
```
**Result:** 2 rows (sarah.chen@acme.com, sarah@example.com)

### 1.6 Lookup a moment
```sql
-- LOOKUP "Q4 2024 Team Retrospective" FROM moments
SELECT name, moment_type FROM moments WHERE name = 'Q4 2024 Team Retrospective';
```
**Result:** 1 row (meeting)

### 1.7 Lookup a benzodiazepine
```sql
-- LOOKUP "Lorazepam"
SELECT name, category FROM resources WHERE name = 'Lorazepam';
```
**Result:** 2 rows (anxiolytic, drug.psychotropic.anxiolytic)

### 1.8 Lookup multiple medications at once
```sql
-- LOOKUP ["Fluoxetine", "Sertraline", "Paroxetine"]
SELECT name, category FROM resources
WHERE name IN ('Fluoxetine', 'Sertraline', 'Paroxetine');
```
**Result:** 6 rows (3 drugs × 2 categories each)

### 1.9 Lookup a mood stabilizer
```sql
-- LOOKUP "Lamotrigine"
SELECT name, category FROM resources WHERE name = 'Lamotrigine';
```
**Result:** 2 rows (mood-stabilizer, drug.psychotropic.mood_stabilizer)

### 1.10 Lookup a treatment guide page
```sql
-- LOOKUP "ASAM Medicaid Coverage Guide - Page 8"
SELECT name, category FROM resources
WHERE name = 'ASAM Medicaid Coverage Guide - Page 8';
```
**Result:** 1 row (treatment-guide)

---

## Batch 2: SEARCH Queries - Semantic Vector Search (10 queries)

Semantic search using pgvector embeddings with cosine similarity.
Uses existing embeddings as proxy vectors for demonstration.

### 2.1 Search for anxiety treatment options
```sql
-- SEARCH "anxiety treatment medications" FROM resources LIMIT 10
-- Uses Lorazepam's embedding as semantic anchor
WITH anxiety_drug AS (
    SELECT e.embedding
    FROM embeddings_resources e
    JOIN resources r ON r.id = e.entity_id
    WHERE r.name = 'Lorazepam' AND e.field_name = 'content'
    LIMIT 1
)
SELECT r.name, r.category,
       1 - (e.embedding <=> (SELECT embedding FROM anxiety_drug)) as similarity
FROM resources r
JOIN embeddings_resources e ON r.id = e.entity_id
WHERE e.field_name = 'content'
ORDER BY e.embedding <=> (SELECT embedding FROM anxiety_drug)
LIMIT 10;
```
**Result:** Lorazepam (1.0), Clonazepam (0.85), Alprazolam (0.78), Zolpidem (0.75), Temazepam (0.73), Diazepam (0.72), Oxazepam (0.72), Clorazepate (0.72)

### 2.2 Search for depression medication information
```sql
-- SEARCH "selective serotonin medications for depression" FROM resources LIMIT 10
-- Uses Sertraline's embedding as semantic anchor
WITH ssri_drug AS (
    SELECT e.embedding
    FROM embeddings_resources e
    JOIN resources r ON r.id = e.entity_id
    WHERE r.name = 'Sertraline' AND e.field_name = 'content'
    AND r.category = 'drug.psychotropic.ssri'
    LIMIT 1
)
SELECT r.name, r.category,
       1 - (e.embedding <=> (SELECT embedding FROM ssri_drug)) as similarity
FROM resources r
JOIN embeddings_resources e ON r.id = e.entity_id
WHERE e.field_name = 'content'
ORDER BY e.embedding <=> (SELECT embedding FROM ssri_drug)
LIMIT 10;
```
**Result:** Sertraline (1.0), Escitalopram (0.86), Fluoxetine (0.85), Citalopram (0.83), Paroxetine (0.83), Vilazodone (0.81), Vortioxetine (0.79), Venlafaxine (0.78), Fluvoxamine (0.78)

### 2.3 Search for crisis intervention protocols
```sql
-- SEARCH "crisis intervention suicide risk assessment" FROM resources LIMIT 10
WITH crisis_resource AS (
    SELECT e.embedding
    FROM embeddings_resources e
    JOIN resources r ON r.id = e.entity_id
    WHERE r.category = 'crisis'
    LIMIT 1
)
SELECT r.name, r.category,
       1 - (e.embedding <=> (SELECT embedding FROM crisis_resource)) as similarity
FROM resources r
JOIN embeddings_resources e ON r.id = e.entity_id
WHERE e.field_name = 'content'
ORDER BY e.embedding <=> (SELECT embedding FROM crisis_resource)
LIMIT 10;
```
**Result:** Crisis Response Guidelines 2025 pages (0.82-0.79 similarity)

### 2.4 Search for substance use disorder treatments
```sql
-- SEARCH "opioid addiction medication assisted treatment" FROM resources LIMIT 10
WITH substance_tx AS (
    SELECT e.embedding
    FROM embeddings_resources e
    JOIN resources r ON r.id = e.entity_id
    WHERE r.name = 'Acamprosate' AND e.field_name = 'content'
    LIMIT 1
)
SELECT r.name, r.category,
       1 - (e.embedding <=> (SELECT embedding FROM substance_tx)) as similarity
FROM resources r
JOIN embeddings_resources e ON r.id = e.entity_id
WHERE e.field_name = 'content'
ORDER BY e.embedding <=> (SELECT embedding FROM substance_tx)
LIMIT 10;
```
**Result:** Acamprosate (1.0), Disulfiram (0.66), Varenicline (0.64), Valproate (0.63), Naltrexone (0.62), Methadone (0.62)

### 2.5 Search for trauma-informed care guidance
```sql
-- SEARCH "trauma informed care behavioral health" FROM resources LIMIT 10
WITH trauma_guide AS (
    SELECT e.embedding
    FROM embeddings_resources e
    JOIN resources r ON r.id = e.entity_id
    WHERE r.name LIKE '%TIP 57%' AND e.field_name = 'content'
    LIMIT 1
)
SELECT r.name, r.category,
       1 - (e.embedding <=> (SELECT embedding FROM trauma_guide)) as similarity
FROM resources r
JOIN embeddings_resources e ON r.id = e.entity_id
WHERE e.field_name = 'content'
ORDER BY e.embedding <=> (SELECT embedding FROM trauma_guide)
LIMIT 10;
```
**Result:** TIP 57 pages with 0.87-0.90 similarity

### 2.6 Search for care coordination roles
```sql
-- SEARCH "patient care coordination case management" FROM resources LIMIT 10
WITH care_role AS (
    SELECT e.embedding
    FROM embeddings_resources e
    JOIN resources r ON r.id = e.entity_id
    WHERE r.name = 'Case Manager' AND e.field_name = 'content'
    LIMIT 1
)
SELECT r.name, r.category,
       1 - (e.embedding <=> (SELECT embedding FROM care_role)) as similarity
FROM resources r
JOIN embeddings_resources e ON r.id = e.entity_id
WHERE e.field_name = 'content'
ORDER BY e.embedding <=> (SELECT embedding FROM care_role)
LIMIT 10;
```
**Result:** Case Manager (1.0), Peer Support Specialist (0.68), Clinical Social Worker (0.67), Addiction Counselor (0.66), Professional Counselor (0.61)

### 2.7 Search for antipsychotic medications
```sql
-- SEARCH "antipsychotic second generation atypical" FROM resources LIMIT 10
WITH antipsych AS (
    SELECT e.embedding
    FROM embeddings_resources e
    JOIN resources r ON r.id = e.entity_id
    WHERE r.name = 'Quetiapine' AND e.field_name = 'content'
    LIMIT 1
)
SELECT r.name, r.category,
       1 - (e.embedding <=> (SELECT embedding FROM antipsych)) as similarity
FROM resources r
JOIN embeddings_resources e ON r.id = e.entity_id
WHERE e.field_name = 'content'
ORDER BY e.embedding <=> (SELECT embedding FROM antipsych)
LIMIT 10;
```
**Result:** Quetiapine (1.0), Risperidone (0.77), Aripiprazole (0.75), Olanzapine (0.74)

### 2.8 Search for treatment planning resources
```sql
-- SEARCH "comprehensive assessment treatment planning" FROM resources LIMIT 10
WITH treatment_plan AS (
    SELECT e.embedding
    FROM embeddings_resources e
    JOIN resources r ON r.id = e.entity_id
    WHERE r.name = 'Treatment Planning' AND e.field_name = 'content'
    LIMIT 1
)
SELECT r.name, r.category,
       1 - (e.embedding <=> (SELECT embedding FROM treatment_plan)) as similarity
FROM resources r
JOIN embeddings_resources e ON r.id = e.entity_id
WHERE e.field_name = 'content'
ORDER BY e.embedding <=> (SELECT embedding FROM treatment_plan)
LIMIT 10;
```
**Result:** Treatment Planning (1.0), Comprehensive Assessment (0.75), Active Treatment (0.70)

### 2.9 Search for co-occurring disorder treatment
```sql
-- SEARCH "dual diagnosis substance use mental health" FROM resources LIMIT 10
WITH cooccur AS (
    SELECT e.embedding
    FROM embeddings_resources e
    JOIN resources r ON r.id = e.entity_id
    WHERE r.name LIKE '%TIP 42%Co-Occurring%' AND e.field_name = 'content'
    LIMIT 1
)
SELECT r.name, r.category,
       1 - (e.embedding <=> (SELECT embedding FROM cooccur)) as similarity
FROM resources r
JOIN embeddings_resources e ON r.id = e.entity_id
WHERE e.field_name = 'content'
ORDER BY e.embedding <=> (SELECT embedding FROM cooccur)
LIMIT 10;
```
**Result:** TIP 42 pages with 0.90-0.93 similarity

### 2.10 Search for patient discharge planning
```sql
-- SEARCH "discharge planning recovery support transitions" FROM resources LIMIT 10
WITH discharge AS (
    SELECT e.embedding
    FROM embeddings_resources e
    JOIN resources r ON r.id = e.entity_id
    WHERE r.name = 'Discharge Planning' AND e.field_name = 'content'
    LIMIT 1
)
SELECT r.name, r.category,
       1 - (e.embedding <=> (SELECT embedding FROM discharge)) as similarity
FROM resources r
JOIN embeddings_resources e ON r.id = e.entity_id
WHERE e.field_name = 'content'
ORDER BY e.embedding <=> (SELECT embedding FROM discharge)
LIMIT 10;
```
**Result:** Discharge Planning (1.0), Recovery Support & Monitoring (0.71), Treatment Planning (0.70), Active Treatment (0.66)

---

## Batch 3: SQL Queries (10 queries)

Direct PostgreSQL queries for complex filtering and aggregations.

### 3.1 List all drugs with boxed warnings sorted by adverse reports
```sql
SELECT name,
       metadata->>'drug_class' as drug_class,
       metadata->>'total_adverse_reports' as adverse_reports
FROM resources
WHERE (metadata->>'has_boxed_warning')::boolean = true
ORDER BY (metadata->>'total_adverse_reports')::int DESC NULLS LAST
LIMIT 10;
```
**Result:**
| name | drug_class | adverse_reports |
|------|------------|-----------------|
| Lorazepam | Benzodiazepine | 207917 |
| Clonazepam | Benzodiazepine | 188473 |
| Quetiapine | Second-Generation Antipsychotic | 183782 |
| Sertraline | SSRI | 182988 |
| Trazodone | Atypical Antidepressant | 179227 |
| Alprazolam | Benzodiazepine | 166270 |
| Citalopram | SSRI | 157304 |
| Amitriptyline | TCA | 148026 |
| Venlafaxine | SNRI | 134382 |
| Diazepam | Benzodiazepine | 130505 |

### 3.2 Find drugs with suicidal ideation as adverse event
```sql
SELECT name, metadata->>'drug_class' as drug_class
FROM resources
WHERE metadata::text LIKE '%SUICIDAL IDEATION%'
LIMIT 10;
```
**Result:** 8 drugs including Brexpiprazole, Fluvoxamine, Vortioxetine, Clomipramine, Aripiprazole, Cariprazine, Lemborexant, Varenicline

### 3.3 Count resources by drug class
```sql
SELECT metadata->>'drug_class' as drug_class, COUNT(*) as count
FROM resources
WHERE metadata->>'drug_class' IS NOT NULL
GROUP BY metadata->>'drug_class'
ORDER BY count DESC;
```
**Result:** 20 drug classes - Second-Gen Antipsychotic (14), Benzodiazepine (13), SSRI (13), Sedative-Hypnotic (8), TCA (8), First-Gen Antipsychotic (8)

### 3.4 SSRI medications ranked by adverse event counts
```sql
SELECT name,
       metadata->>'rxcui' as rxcui,
       metadata->>'total_adverse_reports' as total_reports,
       metadata->'top_adverse_events'->0->>'term' as top_adverse_event
FROM resources
WHERE category = 'drug.psychotropic.ssri'
ORDER BY (metadata->>'total_adverse_reports')::int DESC NULLS LAST;
```
**Result:**
| name | rxcui | total_reports | top_adverse_event |
|------|-------|---------------|-------------------|
| Sertraline | 208149 | 182988 | DRUG INEFFECTIVE |
| Citalopram | 213344 | 157304 | FATIGUE |
| Fluoxetine | 104849 | 114788 | DRUG INEFFECTIVE |
| Escitalopram | 352272 | 106151 | DRUG INEFFECTIVE |
| Paroxetine | 1430128 | 80352 | DRUG INEFFECTIVE |
| Vortioxetine | 1790886 | 13006 | NAUSEA |
| Fluvoxamine | 903873 | 9199 | DRUG INTERACTION |
| Vilazodone | 1653470 | 2534 | DIARRHOEA |

### 3.5 Resources created in the last 7 days
```sql
SELECT name, category, created_at
FROM resources
WHERE created_at > NOW() - INTERVAL '7 days'
ORDER BY created_at DESC
LIMIT 10;
```
**Result:** Project Plan, Meeting Notes, siggy agent, Frontend Component Refactor, Q4 2024 Retrospective Notes, API Design Document v2, TIP 57 pages

### 3.6 List all care stages with content preview
```sql
SELECT name, substring(content, 1, 200) as content_preview
FROM resources
WHERE category = 'care.stage'
ORDER BY name;
```
**Result:** 7 stages - Active Treatment, Comprehensive Assessment, Discharge Planning, Recovery Support & Monitoring, Screening & Access, Transition / Step-Down, Treatment Planning

### 3.7 TIP 42 Co-Occurring Disorders treatment guide pages
```sql
SELECT name
FROM resources
WHERE category = 'treatment-guide'
  AND name LIKE '%TIP 42%'
ORDER BY name
LIMIT 10;
```
**Result:** TIP 42 pages 100-110 (sorted alphabetically)

### 3.8 All antipsychotics sorted by adverse reports
```sql
SELECT name,
       metadata->>'drug_class' as drug_class,
       metadata->>'total_adverse_reports' as total_reports,
       metadata->>'has_boxed_warning' as boxed_warning
FROM resources
WHERE category LIKE 'drug.psychotropic.antipsychotic%'
   OR metadata->>'drug_class' LIKE '%Antipsychotic%'
ORDER BY (metadata->>'total_adverse_reports')::int DESC NULLS LAST
LIMIT 10;
```
**Result:**
| name | drug_class | total_reports | boxed_warning |
|------|------------|---------------|---------------|
| Quetiapine | Second-Generation Antipsychotic | 183782 | true |
| Risperidone | Second-Generation Antipsychotic | 96400 | true |
| Olanzapine | Second-Generation Antipsychotic | 93564 | true |
| Clozapine | Second-Generation Antipsychotic | 92236 | true |
| Aripiprazole | Second-Generation Antipsychotic | 56894 | true |
| Haloperidol | First-Generation Antipsychotic | 37566 | true |

### 3.9 Aggregate adverse events across all drugs
```sql
WITH adverse_events AS (
  SELECT name,
         jsonb_array_elements(metadata->'top_adverse_events') as event
  FROM resources
  WHERE metadata->'top_adverse_events' IS NOT NULL
)
SELECT event->>'term' as adverse_event,
       COUNT(*) as drugs_with_event,
       SUM((event->>'count')::int) as total_reports
FROM adverse_events
GROUP BY event->>'term'
ORDER BY total_reports DESC
LIMIT 15;
```
**Result:**
| adverse_event | drugs_with_event | total_reports |
|---------------|------------------|---------------|
| DRUG INEFFECTIVE | 89 | 222908 |
| FATIGUE | 57 | 150654 |
| NAUSEA | 60 | 147525 |
| OFF LABEL USE | 61 | 125269 |
| TOXICITY TO VARIOUS AGENTS | 48 | 102945 |
| HEADACHE | 44 | 102206 |
| COMPLETED SUICIDE | 23 | 50217 |
| ANXIETY | 28 | 42874 |

### 3.10 Find drugs with RxNorm source data
```sql
SELECT name, metadata->>'rxcui' as rxcui
FROM resources
WHERE metadata->'sources' @> '[{"source_id": "rxnorm"}]'
LIMIT 10;
```
**Result:** 10 drugs with RxNorm IDs (Brexpiprazole: 1658325, Viloxazine: 2536554, etc.)

---

## TRAVERSE Queries - Graph Exploration

### T1. Find all resources with graph edges
```sql
SELECT name, jsonb_array_length(graph_edges) as edge_count,
       graph_edges
FROM resources
WHERE jsonb_array_length(graph_edges) > 0;
```
**Result:** 5 resources with edges (API Design Document v2, Q4 2024 Retrospective Notes, Frontend Component Refactor, Meeting Notes, Project Plan)

### T2. List all relationship types in the graph
```sql
SELECT DISTINCT edge->>'rel_type' as relationship
FROM resources r,
     jsonb_array_elements(r.graph_edges) as edge
WHERE jsonb_array_length(r.graph_edges) > 0;
```
**Result:** 8 edge types - authored_by, reviewed_by, supersedes, facilitator, derived_from, paired_with, documented_in, referenced_by

### T3. Traverse: Find documents authored/facilitated by Sarah Chen
```sql
-- Find resources linked to Sarah Chen's UUID
SELECT r.name, r.category,
       edge->>'rel_type' as relationship,
       edge->>'weight' as weight
FROM resources r,
     jsonb_array_elements(r.graph_edges) as edge
WHERE edge->>'dst' LIKE '%bb55c781%';
```
**Result:** API Design Document v2 (authored_by, 1.0), Q4 2024 Retrospective Notes (facilitator, 1.0)

### T4. Traverse: Explore all edges from API Design Document v2
```sql
SELECT r.name as source, r.category,
       edge->>'dst' as target_id,
       edge->>'rel_type' as relationship
FROM resources r,
     jsonb_array_elements(r.graph_edges) as edge
WHERE r.name = 'API Design Document v2';
```
**Result:** 3 edges - authored_by (Sarah), reviewed_by (Mike), supersedes (older doc)

---

## Metadata Structure Reference

### Drug Resource Metadata
```json
{
  "rxcui": "1658325",
  "drug_class": "Second-Generation Antipsychotic",
  "drug_class_code": "atypical_antipsychotic",
  "is_psychotropic": true,
  "has_boxed_warning": true,
  "total_adverse_reports": 3083,
  "top_adverse_events": [
    {"rank": 1, "term": "DRUG INEFFECTIVE", "count": 225},
    {"rank": 2, "term": "DEATH", "count": 214},
    {"rank": 3, "term": "DRUG INTERACTION", "count": 166}
  ],
  "sources": [
    {"source_id": "rxnorm", "source_name": "RxNorm", "source_url": "https://rxnav.nlm.nih.gov/REST/rxcui/1658325"},
    {"source_id": "openfda_faers", "source_name": "openFDA FAERS", "record_count": 3083}
  ]
}
```

### Graph Edge Format
```json
{
  "dst": "bb55c781-f880-594a-82e5-5191f0b64be8",
  "weight": 1.0,
  "rel_type": "authored_by",
  "created_at": "2025-11-28T15:45:11.921188",
  "properties": {}
}
```

---

## Summary

- **30 verified queries** across LOOKUP, SEARCH, and SQL patterns
- **843 resources** with vector embeddings for semantic search
- **8 relationship types** in the graph
- **20 drug classes** with adverse event data from openFDA FAERS
- **4 treatment guide sources**: TIP 42 (Co-Occurring), TIP 57 (Trauma), ASAM, Crisis Response 2025
