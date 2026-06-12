# Database Choice - Text Analyzer

## My Choice
Azure Cosmos DB for NoSQL, running in **Serverless** capacity mode.

## Justification
My Text Analyzer returns its results as a JSON object with nested `analysis`
and `metadata` sections. Cosmos DB for NoSQL stores JSON documents natively,
so I can save the result dictionary directly without flattening it or
defining a schema first. It has a well-supported Python SDK (`azure-cosmos`)
that integrates cleanly with an Azure Function, and serverless capacity mode
means I only pay for the request units I actually consume, with no minimum
charge - which fits both a student budget and the serverless theme of this
course. Cosmos DB also lets me query stored results with SQL-like syntax,
which I need for the GetAnalysisHistory endpoint.

## Alternatives Considered
- **Azure Table Storage** - cheap, but it stores flat key-value rows. My
  results are nested JSON, so I'd have to serialize them into strings and
  rebuild them on read. More work for no benefit at this scale.
- **Azure SQL Database** - relational and schema-first. My data is naturally
  a document, so forcing it into tables adds setup and doesn't suit a
  serverless workload.
- **Azure Blob Storage** - I could store each result as a JSON file, but Blob
  has no query layer. The history endpoint needs to retrieve records with a
  limit, which Blob can't do without building my own indexing.

## Cost Considerations
Cosmos DB serverless has no minimum cost - billing is roughly $0.25 per
million request units consumed, plus storage per GB. For a lab running a
handful of analyses, this is a few cents at most. I chose serverless over
the lifetime free tier (1000 RU/s + 25 GB free) because free tier isn't
available for serverless accounts and is limited to one per subscription -
serverless is cheaper for my sporadic usage and keeps the free-tier slot open.
