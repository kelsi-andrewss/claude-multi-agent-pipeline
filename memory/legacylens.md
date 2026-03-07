# LegacyLens Project Memory

## Deployment
- Production URL: https://legacylens-b06nvam8b-kelsiandrews-3963s-projects.vercel.app
- GitHub: https://github.com/kelsi-andrewss/legacylens
- Vercel project name: legacylens
- Get latest prod URL programmatically: `curl "https://api.vercel.com/v9/projects/legacylens/deployments?limit=1&target=production" -H "Authorization: Bearer $VERCEL_TOKEN"`

## Stack
- Frontend: Next.js 16, Tailwind, react-syntax-highlighter
- Vector DB: Pinecone (index: legacylens, 7,759 vectors, cosine, 1536 dims)
- Embeddings: text-embedding-3-small
- LLM: GPT-4o-mini (streaming)
- Ingestion: Python, custom Fortran parser, cache at ingestion/cache/

## Index
- 2,329 Fortran files, 2,317 routines parsed, 7,759 chunks
- Metadata fields: subroutine_name, kind, file_path, line_start, line_end, parameters, dependencies, data_type_prefix, category, text
- Source: LAPACK at data/lapack/ (Reference-LAPACK/lapack on GitHub)

## Key Files
- ingestion/ingest.py — ingestion pipeline (BATCH_SIZE=10, sleep=2s for TPM limits)
- ingestion/parser.py — Fortran parser
- src/app/api/query/route.ts — RAG query endpoint
- src/lib/prompts.ts — 4 modes: explain, dependencies, docs, translate
- src/components/CodeSnippet.tsx — renders retrieved chunks with syntax highlighting
- docs/ — architecture.md, cost-analysis.md, evaluation.md, presearch docs

## Gaps Remaining (as of 2026-03-03)
- README needs setup guide + deployed URL
- Drill-down into full file context (CodeSnippet feature)
- Demo video (user records)
- Social post (user posts)
