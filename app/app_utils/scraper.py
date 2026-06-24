import os
import tempfile
import urllib.request

import arxiv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from pypdf import PdfReader

# Default User Interest Profile
DEFAULT_INTEREST_PROFILE = (
    "System Design, Distributed Systems, Databases, Software Engineering, "
    "AI/ML Infrastructure, Large Language Models (LLM), Generative AI (GenAI), "
    "and Artificial Intelligence and Machine Learning (AI and ML)."
)


class RelevanceScore(BaseModel):
    relevance_score: float = Field(
        ...,
        description="Relevance score from 0.0 to 1.0 indicating how well the paper matches the interest profile.",
    )
    reason: str = Field(
        ...,
        description="A 1-2 sentence explanation of why the paper is relevant or not.",
    )


def search_arxiv_papers(max_results: int = 15) -> list[dict]:
    """Search arXiv for recent papers in CS systems and AI categories."""
    # Configure a custom client with delay and retries to prevent HTTP 429
    client = arxiv.Client(
        page_size=max_results,
        delay_seconds=3.0,
        num_retries=5
    )
    # Query for Distributed (cs.DC), DB (cs.DB), SE (cs.SE), AI (cs.AI), LG (cs.LG)
    query = "cat:cs.DC OR cat:cs.DB OR cat:cs.SE OR cat:cs.AI OR cat:cs.LG"

    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers = []
    try:
        for result in client.results(search):
            papers.append(
                {
                    "arxiv_id": result.entry_id.split("/abs/")[-1].split("v")[
                        0
                    ],  # clean ID without version suffix
                    "version_url": result.entry_id,
                    "title": result.title,
                    "summary": result.summary,
                    "authors": [author.name for author in result.authors],
                    "pdf_url": result.pdf_url,
                    "published": result.published.isoformat(),
                }
            )
    except Exception as e:
        print(f"Error querying arXiv papers: {e}. Using fallback papers.")
        return [
            {
                "arxiv_id": "2303.08774",
                "version_url": "https://arxiv.org/abs/2303.08774",
                "title": "GPT-4 Technical Report",
                "summary": "We report the development of GPT-4, a large-scale, multimodal model which can accept image and text inputs and produce text outputs.",
                "authors": ["OpenAI"],
                "pdf_url": "https://arxiv.org/pdf/2303.08774",
                "published": "2023-03-15T00:00:00",
            },
            {
                "arxiv_id": "1706.03762",
                "version_url": "https://arxiv.org/abs/1706.03762",
                "title": "Attention Is All You Need",
                "summary": "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.",
                "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit", "Llion Jones", "Aidan N. Gomez", "Lukasz Kaiser", "Illia Polosukhin"],
                "pdf_url": "https://arxiv.org/pdf/1706.03762",
                "published": "2017-06-12T00:00:00",
            },
            {
                "arxiv_id": "2005.14165",
                "version_url": "https://arxiv.org/abs/2005.14165",
                "title": "Language Models are Few-Shot Learners",
                "summary": "We train GPT-3, an autoregressive language model with 175 billion parameters, and test its performance on a variety of NLP tasks.",
                "authors": ["Tom B. Brown", "Benjamin Mann", "Nick Ryder", "Melanie Subbiah", "Jared Kaplan"],
                "pdf_url": "https://arxiv.org/pdf/2005.14165",
                "published": "2020-05-28T00:00:00",
            }
        ]
    return papers


def score_paper_relevance(
    title: str, abstract: str, interest_profile: str = DEFAULT_INTEREST_PROFILE
) -> RelevanceScore:
    """Use Gemini to score how relevant a paper's abstract is to the user's interest profile."""
    # Ensure client uses Vertex AI or API key as configured in environment
    client = genai.Client()

    prompt = f"""
    Evaluate the relevance of the following research paper to the user's interest profile.

    User Interest Profile:
    {interest_profile}

    Paper Title:
    {title}

    Paper Abstract:
    {abstract}

    Provide a score between 0.0 (completely irrelevant) and 1.0 (highly relevant, a must-read).
    Be moderately lenient; award scores above 0.65 to papers that directly focus on systems architecture,
    large scale distributed systems, database design, software engineering, AI/ML infrastructure,
    Large Language Models (LLM), Generative AI (GenAI), or AI and ML.
    """

    # Use gemini-3.5-flash for fast and cost-effective relevance classification
    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RelevanceScore,
            temperature=0.0,
        ),
    )

    try:
        # Load structured output
        return RelevanceScore.model_validate_json(response.text)
    except Exception as e:
        # Fallback in case of parse issues
        return RelevanceScore(
            relevance_score=0.0, reason=f"Failed to parse score: {e!s}"
        )


def download_and_extract_pdf_text(pdf_url: str, max_chars: int = 40000) -> str:
    """Download paper PDF and extract text up to a maximum number of characters."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_pdf_path = os.path.join(temp_dir, "temp_paper.pdf")

            # Download the PDF file
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            req = urllib.request.Request(pdf_url, headers=headers)
            with (
                urllib.request.urlopen(req) as response,
                open(temp_pdf_path, "wb") as out_file,
            ):
                out_file.write(response.read())

            # Extract text using pypdf
            reader = PdfReader(temp_pdf_path)
            text_parts = []
            char_count = 0

            for page in reader.pages:
                page_text = page.extract_text() or ""
                char_count += len(page_text)
                text_parts.append(page_text)
                if char_count >= max_chars:
                    break

            full_text = "\n".join(text_parts)
            return full_text[:max_chars]
    except Exception as e:
        print(f"Error downloading or parsing PDF from {pdf_url}: {e}")
        return ""


def search_classic_arxiv_papers(max_results: int = 3) -> list[dict]:
    """Search arXiv for popular/classic older papers by sorting by relevance on historical key topics."""
    import random
    classic_topics = [
        "MapReduce distributed database",
        "Raft Paxos consensus distributed",
        "Google Spanner database",
        "Transformer Attention deep learning",
        "BERT pre-training language models",
        "ResNet deep residual learning",
        "Adam optimizer deep learning",
        "FlashAttention fast attention"
    ]
    # Pick a random classic topic to keep recommendations diverse
    topic = random.choice(classic_topics)
    
    # Configure a custom client with delay and retries
    client = arxiv.Client(
        page_size=max_results,
        delay_seconds=3.0,
        num_retries=5
    )
    
    # Query for classic papers using relevance sorting
    search = arxiv.Search(
        query=topic,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )

    papers = []
    try:
        for result in client.results(search):
            papers.append(
                {
                    "arxiv_id": result.entry_id.split("/abs/")[-1].split("v")[0],
                    "version_url": result.entry_id,
                    "title": result.title,
                    "summary": result.summary,
                    "authors": [author.name for author in result.authors],
                    "pdf_url": result.pdf_url,
                    "published": result.published.isoformat(),
                    "is_classic": True,
                }
            )
    except Exception as e:
        print(f"Error querying classic arXiv papers: {e}. Using fallback classic papers.")
    
    if not papers:
        return [
            {
                "arxiv_id": "1706.03762",
                "version_url": "https://arxiv.org/abs/1706.03762",
                "title": "Attention Is All You Need",
                "summary": "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.",
                "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit", "Llion Jones", "Aidan N. Gomez", "Lukasz Kaiser", "Illia Polosukhin"],
                "pdf_url": "https://arxiv.org/pdf/1706.03762",
                "published": "2017-06-12T00:00:00",
                "is_classic": True
            }
        ]
    return papers
