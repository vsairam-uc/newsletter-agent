# ruff: noqa: E402
import os
import sys

from dotenv import load_dotenv

load_dotenv()
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

# Add project path to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import ADK elements
from google.adk.runners import InMemoryRunner
from google.genai import types

# Import local elements
from pydantic import BaseModel

from app.agent import app as adk_app
from app.app_utils.db import (
    add_subscriber,
    get_newsletter,
    get_newsletters,
    init_db,
    remove_subscriber,
)

app = FastAPI(title="Systems & AI Research Digest")

# Set up templates directory
templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)


@app.on_event("startup")
async def startup_event():
    """Run database initialization on startup."""
    init_db()


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Render home page with all archived publications."""
    try:
        newsletters = get_newsletters()
        return templates.TemplateResponse(
            request=request, name="home.html", context={"newsletters": newsletters}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e!s}") from e


@app.get("/newsletter/{newsletter_id}", response_class=HTMLResponse)
async def read_newsletter(request: Request, newsletter_id: int):
    """Render detailed view of a specific archived newsletter."""
    newsletter = get_newsletter(newsletter_id)
    if not newsletter:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    return templates.TemplateResponse(
        request=request, name="post.html", context={"newsletter": newsletter}
    )


@app.post("/api/trigger")
async def trigger_curation():
    """Programmatically run the ADK 2.0 multi-agent workflow to generate and dispatch newsletter."""
    try:
        runner = InMemoryRunner(app=adk_app)

        # Create a new run session
        session = await runner.session_service.create_session(
            app_name="app", user_id="manual_trigger"
        )

        curation_result = None

        # Run the workflow graph asynchronously
        async for event in runner.run_async(
            user_id="manual_trigger",
            session_id=session.id,
            new_message=types.Content(
                role="user", parts=[types.Part.from_text(text="Trigger Run")]
            ),
        ):
            # Capture final output from the curator node
            if event.output is not None:
                curation_result = event.output

        if curation_result and curation_result.get("status") == "success":
            return JSONResponse(content=curation_result)
        elif curation_result and curation_result.get("status") == "skipped":
            return JSONResponse(
                status_code=200,
                content={
                    "status": "skipped",
                    "reason": curation_result.get("reason", "No relevant papers"),
                },
            )
        else:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Curation completed but did not return success status."
                },
            )

    except Exception as e:
        import traceback

        print(traceback.format_exc())
        return JSONResponse(
            status_code=500, content={"error": f"Workflow execution failed: {e!s}"}
        )


class SubscribeRequest(BaseModel):
    email: str


@app.post("/api/subscribe")
async def subscribe(req: SubscribeRequest):
    email = req.email.strip().lower()
    if not email or "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Invalid email address.")
    success = add_subscriber(email)
    if success:
        return {"status": "success", "message": f"Successfully subscribed {email}."}
    else:
        raise HTTPException(
            status_code=500, detail="Failed to subscribe. Please try again."
        )


@app.post("/api/unsubscribe")
async def unsubscribe(req: SubscribeRequest):
    email = req.email.strip().lower()
    if not email or "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Invalid email address.")
    success = remove_subscriber(email)
    if success:
        return {"status": "success", "message": f"Successfully unsubscribed {email}."}
    else:
        raise HTTPException(
            status_code=500, detail="Failed to unsubscribe. Please try again."
        )
