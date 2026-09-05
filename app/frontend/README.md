# Cloud Architect Assistant — Frontend

Next.js 14 (App Router) frontend for the [Cloud Architect Assistant](https://cloud-architect-assistant.vercel.app).

## What it does

Takes a plain-English description of a system and renders:
- Architecture recommendation with service selection and trade-off reasoning
- Monthly cost breakdown with scale scenarios
- Terraform HCL ready to deploy
- Mermaid architecture diagram
- Multi-agent debate (Cost vs Reliability vs Security agents)
- Drift detection against live AWS / Azure / GCP accounts

Supports AWS, Azure, and GCP.

## Running locally

```bash
npm install
npm run dev        # http://localhost:3000
```

Set `NEXT_PUBLIC_API_URL` in `.env.local` to point at your backend (defaults to the Railway deployment).

## Stack

- Next.js 14 App Router
- TypeScript
- Tailwind CSS
- Vercel (production deployment)
