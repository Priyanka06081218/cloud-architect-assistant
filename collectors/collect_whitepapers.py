# collectors/collect_whitepapers.py
# Downloads AWS whitepapers (PDF) and extracts text page by page

import requests
import json
import os
import pymupdf  # pip install pymupdf
from config import RAW_WHITEPAPERS

# These 10 whitepapers are the highest value for architecture decisions.
# Name is used as the filename. URL is the direct PDF download link.

WHITEPAPERS = [
    {
        "name": "well_architected_framework",
        "url":  "https://docs.aws.amazon.com/pdfs/wellarchitected/latest/framework/wellarchitected-framework.pdf"
    },
    {
        "name": "reliability_pillar",
        "url":  "https://docs.aws.amazon.com/pdfs/wellarchitected/latest/reliability-pillar/wellarchitected-reliability-pillar.pdf"
    },
    {
        "name": "performance_efficiency_pillar",
        "url":  "https://docs.aws.amazon.com/pdfs/wellarchitected/latest/performance-efficiency-pillar/wellarchitected-performance-efficiency-pillar.pdf"
    },
    {
        "name": "cost_optimization_pillar",
        "url":  "https://docs.aws.amazon.com/pdfs/wellarchitected/latest/cost-optimization-pillar/wellarchitected-cost-optimization-pillar.pdf"
    },
    {
        "name": "security_pillar",
        "url":  "https://docs.aws.amazon.com/pdfs/wellarchitected/latest/security-pillar/wellarchitected-security-pillar.pdf"
    },
    {
        "name": "microservices_on_aws",
        "url":  "https://docs.aws.amazon.com/pdfs/whitepapers/latest/microservices-on-aws/microservices-on-aws.pdf"
    },
    {
        "name": "serverless_architectures",
        "url":  "https://docs.aws.amazon.com/pdfs/whitepapers/latest/serverless-multi-tier-architectures-api-gateway-lambda/serverless-multi-tier-architectures-api-gateway-lambda.pdf"
    },
    {
        "name": "disaster_recovery",
        "url":  "https://docs.aws.amazon.com/pdfs/whitepapers/latest/disaster-recovery-workloads-on-aws/disaster-recovery-workloads-on-aws.pdf"
    },
    {
        "name": "running_containers",
        "url":  "https://docs.aws.amazon.com/pdfs/whitepapers/latest/running-containerized-microservices/running-containerized-microservices.pdf"
    },
    {
        "name": "saas_architecture",
        "url":  "https://docs.aws.amazon.com/pdfs/whitepapers/latest/saas-architecture-fundamentals/saas-architecture-fundamentals.pdf"
    },
]


def download_pdf(name, url):
    """Download a PDF and save it locally."""
    
    pdf_path = os.path.join(RAW_WHITEPAPERS, f"{name}.pdf")
    
    print(f"  Downloading: {name}")
    response = requests.get(url, timeout=60)
    
    with open(pdf_path, "wb") as f:
        f.write(response.content)
    
    print(f"  Saved: {pdf_path} ({len(response.content) // 1024} KB)")
    return pdf_path


def extract_text_from_pdf(name, pdf_path):
    """Extract text from each page of the PDF. Save as JSON."""
    
    doc = pymupdf.open(pdf_path)
    pages = []
    
    for page_num, page in enumerate(doc):
        text = page.get_text()
        
        # Skip near-empty pages (table of contents, blank pages)
        if len(text.strip()) < 100:
            continue
        
        pages.append({
            "page":   page_num + 1,
            "text":   text.strip()
        })
    
    output = {
        "source":     "whitepaper",
        "name":       name,
        "total_pages": len(pages),
        "pages":      pages
    }
    
    json_path = os.path.join(RAW_WHITEPAPERS, f"{name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    
    print(f"  Extracted {len(pages)} pages → {json_path}")
    return len(pages)


def run():
    os.makedirs(RAW_WHITEPAPERS, exist_ok=True)
    total_pages = 0
    
    for paper in WHITEPAPERS:
        print(f"\nProcessing: {paper['name']}")
        
        pdf_path = download_pdf(paper["name"], paper["url"])
        pages    = extract_text_from_pdf(paper["name"], pdf_path)
        
        total_pages += pages
    
    print(f"\nTotal pages extracted from whitepapers: {total_pages}")


if __name__ == "__main__":
    run()
