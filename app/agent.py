# Copyright 2026 Google LLC
# ruff: noqa: E402
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import os

from dotenv import load_dotenv

load_dotenv()
from typing import Any

# Local Imports
import google.auth
from google import genai
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event

# ADK 2.0 Imports
from google.adk.workflow import Workflow, node
from google.genai import types
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

from app.app_utils.db import get_active_subscribers, is_paper_processed, save_newsletter
from app.app_utils.mailer import send_newsletter_email
from app.app_utils.scraper import (
    DEFAULT_INTEREST_PROFILE,
    download_and_extract_pdf_text,
    score_paper_relevance,
    search_arxiv_papers,
    search_classic_arxiv_papers,
)

# Ensure Application Default Credentials context is set properly
_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


class PaperAnalysis(BaseModel):
    problem_statement: str = Field(
        description="1-2 sentences summarizing the core problem the paper addresses."
    )
    proposed_architecture: str = Field(
        description="Description of the proposed system architecture, algorithm, or methodology."
    )
    tradeoffs: str = Field(
        description="Key trade-offs, limitations, or performance bottlenecks identified by the authors."
    )
    industry_application: str = Field(
        description="How this paper can be applied in real-world software engineering or AI infrastructure today."
    )


@node
def relevance_filter(ctx: Context, node_input: Any) -> list[dict]:
    """Fetch recent papers and filter them by relevance score."""
    interest_profile = ctx.state.get("interest_profile") or DEFAULT_INTEREST_PROFILE
    print(f"Starting relevance filter using interest profile: {interest_profile}")

    # 1. Fetch recent papers from arXiv
    all_papers = search_arxiv_papers(max_results=20)
    print(f"Fetched {len(all_papers)} papers from arXiv.")

    # 2. Filter out already processed papers
    new_papers = [p for p in all_papers if not is_paper_processed(p["arxiv_id"])]
    print(f"Found {len(new_papers)} new papers that haven't been curated yet.")

    # 3. Score relevance of recent papers using Gemini
    relevant_papers = []
    candidate_papers = []
    for paper in new_papers:
        score_res = score_paper_relevance(
            paper["title"], paper["summary"], interest_profile
        )
        score = score_res.relevance_score
        print(f"Recent Paper: '{paper['title']}' | Score: {score}")
        
        paper["relevance_score"] = score
        paper["relevance_reason"] = score_res.reason
        paper["is_classic"] = False

        if score >= 0.65:
            relevant_papers.append(paper)
        else:
            candidate_papers.append(paper)

    # 4. Fetch and score classic papers
    classic_papers = search_classic_arxiv_papers(max_results=3)
    new_classic_papers = [p for p in classic_papers if not is_paper_processed(p["arxiv_id"])]
    print(f"Found {len(new_classic_papers)} new classic/older papers.")

    relevant_classics = []
    for paper in new_classic_papers:
        score_res = score_paper_relevance(
            paper["title"], paper["summary"], interest_profile
        )
        score = score_res.relevance_score
        print(f"Classic Paper: '{paper['title']}' | Score: {score}")

        paper["relevance_score"] = score
        paper["relevance_reason"] = score_res.reason

        # Slightly more lenient threshold for classic papers since they are already known classics
        if score >= 0.60:
            relevant_classics.append(paper)
        else:
            candidate_papers.append(paper)

    # Combine recent and classic relevant papers
    combined_relevant = relevant_papers + relevant_classics

    # 5. Fallback mechanism: if total papers are fewer than 3, select next best candidate papers
    if len(combined_relevant) < 3 and candidate_papers:
        # Sort remaining candidates by score descending
        candidate_papers.sort(key=lambda x: x.get("relevance_score", 0.0), reverse=True)
        for paper in candidate_papers:
            combined_relevant.append(paper)
            print(f"Fallback: added paper '{paper['title']}' with score {paper['relevance_score']}")
            if len(combined_relevant) >= 3:
                break

    # Limit to top 5 papers per run to keep digest readable
    final_papers = combined_relevant[:5]
    print(f"Relevance filter selected {len(final_papers)} papers.")
    return final_papers


@node
def academic_summarizer(ctx: Context, node_input: list[dict]) -> list[dict]:
    """Download PDFs and generate detailed academic summaries using Gemini."""
    if not node_input:
        print("No relevant papers found to summarize.")
        return []

    client = genai.Client()
    summarized_papers = []

    for paper in node_input:
        print(f"Downloading and extracting PDF text for: '{paper['title']}'")
        # Extract text from the PDF
        pdf_text = download_and_extract_pdf_text(paper["pdf_url"], max_chars=30000)

        if not pdf_text:
            print(
                f"Failed to extract PDF text for '{paper['title']}'. Falling back to abstract."
            )
            pdf_text = paper["summary"]

        # Call Gemini for structured analysis
        prompt = f"""
        Analyze the following academic research paper text and extract:
        1. The core problem statement.
        2. The proposed system architecture or technical design.
        3. The key trade-offs, limitations, or bottlenecks.
        4. Real-world industry applications.

        Paper Title: {paper["title"]}
        Paper Text:
        {pdf_text}
        """

        print(f"Generating academic summary for '{paper['title']}'...")
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PaperAnalysis,
                temperature=0.2,
            ),
        )

        try:
            analysis = PaperAnalysis.model_validate_json(response.text)
            paper.update(
                {
                    "problem_statement": analysis.problem_statement,
                    "proposed_architecture": analysis.proposed_architecture,
                    "tradeoffs": analysis.tradeoffs,
                    "industry_application": analysis.industry_application,
                }
            )
            summarized_papers.append(paper)
        except Exception as e:
            print(f"Error parsing Gemini analysis for '{paper['title']}': {e}")
            # Fallback to abstract/simple fields if parse fails
            paper.update(
                {
                    "problem_statement": paper["summary"][:200] + "...",
                    "proposed_architecture": "See full paper link.",
                    "tradeoffs": "N/A",
                    "industry_application": "Research validation.",
                }
            )
            summarized_papers.append(paper)

    return summarized_papers


@node
def newsletter_curator(ctx: Context, node_input: list[dict]):
    """Format the digest, send email, and archive to SQLite/GCS."""
    if not node_input:
        print("No papers to curate. Newsletter execution skipped.")
        res = {"status": "skipped", "reason": "No relevant papers"}
        yield Event(
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text="No relevant papers found to curate this time."
                    )
                ],
            )
        )
        yield Event(output=res)
        return

    date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    # 1. Generate a catchy, content-aware title
    client = genai.Client()
    titles = [p["title"] for p in node_input]
    prompt = f"Generate a short, professional email newsletter subject line (no quotes, max 60 chars) summarizing these topics: {', '.join(titles)}"
    response = client.models.generate_content(model="gemini-3.5-flash", contents=prompt)
    subject_title = response.text.strip().replace('"', "")
    subject = f"Systems & AI Digest: {subject_title}"

    # 2. Render email HTML template using Jinja2
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("email.html")

    html_content = template.render(title=subject, date=date_str, papers=node_input)

    # 3. Send email to subscribers via Resend (and save backup HTML)
    recipient = ctx.state.get("recipient")
    if not recipient:
        active_subscribers = get_active_subscribers()
        if active_subscribers:
            recipient = active_subscribers
            print(f"Retrieved {len(recipient)} active subscribers from database.")
        else:
            print(
                "No active subscribers found in database. Falling back to default recipient."
            )

    email_dispatched = send_newsletter_email(subject, html_content, recipient)

    # 4. Save to Database (SQLite / GCS)
    newsletter_id = save_newsletter(subject, html_content, node_input)
    print(f"Newsletter successfully archived under ID: {newsletter_id}")

    res = {
        "status": "success",
        "newsletter_id": newsletter_id,
        "title": subject,
        "email_dispatched": email_dispatched,
        "papers_count": len(node_input),
    }

    yield Event(
        content=types.Content(
            role="model",
            parts=[
                types.Part.from_text(
                    text=f"Successfully curated and published the newsletter: '{subject}' containing {len(node_input)} papers."
                )
            ],
        )
    )
    yield Event(output=res)


# ADK 2.0 Workflow Definition
root_agent = Workflow(
    name="newsletter_curator_workflow",
    edges=[
        ("START", relevance_filter),
        (relevance_filter, academic_summarizer),
        (academic_summarizer, newsletter_curator),
    ],
    description="Automated multi-agent workflow to scrape arXiv, relevance-score, summarize PDFs, and dispatch newsletter digests.",
)

app = App(root_agent=root_agent, name="app")
