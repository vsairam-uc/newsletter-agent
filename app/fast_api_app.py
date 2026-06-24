# ruff: noqa: E402
import os
import sys

from dotenv import load_dotenv

load_dotenv()
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
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
    clear_processed_papers_for_today,
    get_active_subscribers,
    get_newsletter,
    get_newsletters,
    init_db,
    remove_subscriber,
)

app = FastAPI(title="Systems & AI Research Digest")

security = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify that the provided bearer token matches the configured ADMIN_API_KEY."""
    admin_key = os.environ.get("ADMIN_API_KEY", "dev-token-key")
    if credentials.credentials != admin_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return credentials.credentials

# Set up templates directory
templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)


@app.on_event("startup")
async def startup_event():
    """Run database initialization on startup."""
    init_db()


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, page: int = 1):
    """Render home page with all archived publications."""
    try:
        newsletters = get_newsletters()
        per_page = 5
        total_newsletters = len(newsletters)
        total_pages = max(1, (total_newsletters + per_page - 1) // per_page)
        
        # Clamp page number
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_newsletters = newsletters[start_idx:end_idx]
        
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "newsletters": paginated_newsletters,
                "show_trigger": False,
                "page": page,
                "total_pages": total_pages,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e!s}") from e


@app.get("/test", response_class=HTMLResponse)
async def read_test(request: Request, page: int = 1):
    """Render home page with all archived publications, showing the trigger run button."""
    try:
        newsletters = get_newsletters()
        per_page = 5
        total_newsletters = len(newsletters)
        total_pages = max(1, (total_newsletters + per_page - 1) // per_page)
        
        # Clamp page number
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_newsletters = newsletters[start_idx:end_idx]
        
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "newsletters": paginated_newsletters,
                "show_trigger": True,
                "page": page,
                "total_pages": total_pages,
            },
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
async def trigger_curation(token: str = Depends(verify_token)):
    """Programmatically run the ADK 2.0 multi-agent workflow to generate and dispatch newsletter."""
    try:
        # Clear papers processed today to allow re-running
        clear_processed_papers_for_today()

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


@app.get("/api/subscribers")
async def list_subscribers(token: str = Depends(verify_token)):
    """Retrieve all active subscriber email addresses."""
    try:
        subscribers = get_active_subscribers()
        return {"status": "success", "subscribers": subscribers}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve subscribers: {e!s}"
        )

