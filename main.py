import os
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import create_document, get_documents, db
from schemas import Project as ProjectSchema, Asset as AssetSchema, Render as RenderSchema

# Optional heavy imports guarded to avoid startup failure
try:
    from moviepy.editor import VideoFileClip, vfx, AudioFileClip
except Exception:  # pragma: no cover
    VideoFileClip = None
    vfx = None
    AudioFileClip = None

UPLOAD_DIR = os.path.join("static", "uploads")
OUTPUT_DIR = os.path.join("static", "outputs")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="Video Editor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (uploaded assets and rendered outputs)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def read_root():
    return {"message": "Video Editor Backend Running"}


# ---------- Models for responses ----------
class ProjectResponse(BaseModel):
    id: str
    title: str
    description: Optional[str] = None


class AssetResponse(BaseModel):
    id: str
    project_id: str
    filename: str
    url: str
    kind: str
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None


class RenderRequest(BaseModel):
    project_id: str
    asset_id: str
    start: float = 0.0
    end: Optional[float] = None
    speed: float = 1.0
    volume: float = 1.0
    rotate: int = 0  # 0, 90, 180, 270
    resolution_width: Optional[int] = None
    resolution_height: Optional[int] = None


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# ---------- Project Endpoints ----------
@app.post("/projects")
def create_project(title: str = Form(...), description: Optional[str] = Form(None)):
    payload = {"title": title, "description": description}
    project_id = create_document("project", payload)
    return {"id": project_id, "title": title, "description": description}


@app.get("/projects")
def list_projects():
    docs = get_documents("project")
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


# ---------- Asset Upload & List ----------
@app.post("/assets/upload")
async def upload_asset(request: Request, project_id: str = Form(...), file: UploadFile = File(...)):
    if file.content_type is None:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    kind = "video" if file.content_type.startswith("video/") else (
        "audio" if file.content_type.startswith("audio/") else (
            "image" if file.content_type.startswith("image/") else "other"
        )
    )
    if kind == "other":
        raise HTTPException(status_code=400, detail="Only video/audio/image files are supported")

    # Save file to disk
    filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{file.filename}"
    save_path = os.path.join(UPLOAD_DIR, filename)
    with open(save_path, "wb") as f:
        data = await file.read()
        f.write(data)

    # Extract media info if video
    duration = None
    width = None
    height = None
    if kind == "video" and VideoFileClip is not None:
        try:
            clip = VideoFileClip(save_path)
            duration = float(clip.duration) if clip.duration else None
            width, height = clip.w, clip.h
            clip.reader.close()
            if clip.audio:
                try:
                    clip.audio.reader.close_proc()
                except Exception:
                    pass
            clip.close()
        except Exception:
            pass

    public_url = str(request.base_url).rstrip("/") + f"/static/uploads/{filename}"

    asset_doc = {
        "project_id": project_id,
        "filename": file.filename,
        "path": save_path,
        "url": public_url,
        "kind": kind,
        "duration": duration,
        "width": width,
        "height": height,
    }
    asset_id = create_document("asset", asset_doc)

    return {
        "id": asset_id,
        "project_id": project_id,
        "filename": file.filename,
        "url": public_url,
        "kind": kind,
        "duration": duration,
        "width": width,
        "height": height,
    }


@app.get("/projects/{project_id}/assets")
def list_assets(project_id: str):
    docs = get_documents("asset", {"project_id": project_id})
    out = []
    for d in docs:
        d["id"] = str(d.pop("_id"))
        out.append(d)
    return out


# ---------- Render (Export) ----------
@app.post("/render")
def render_video(request: Request, payload: RenderRequest):
    if VideoFileClip is None:
        raise HTTPException(status_code=500, detail="Video processing backend not available")

    # Fetch asset
    asset_docs = get_documents("asset", {"_id": {"$exists": True}, "project_id": payload.project_id})
    asset_doc = None
    for d in asset_docs:
        if str(d.get("_id")) == payload.asset_id:
            asset_doc = d
            break
    if asset_doc is None:
        # Fallback: try to find by matching id string manually
        for d in get_documents("asset", {"project_id": payload.project_id}):
            if str(d.get("_id")) == payload.asset_id:
                asset_doc = d
                break
    if asset_doc is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    source_path = asset_doc.get("path")
    if not source_path or not os.path.exists(source_path):
        raise HTTPException(status_code=404, detail="Source file not found on server")

    try:
        clip = VideoFileClip(source_path)

        # Trim
        start = max(0.0, float(payload.start or 0.0))
        end = float(payload.end) if payload.end else clip.duration
        end = min(end, clip.duration)
        subclip = clip.subclip(start, end)

        # Speed
        if payload.speed and payload.speed != 1.0:
            subclip = subclip.fx(vfx.speedx, payload.speed)

        # Rotate
        rotate_map = {0: 0, 90: 90, 180: 180, 270: 270}
        r = rotate_map.get(int(payload.rotate or 0), 0)
        if r:
            subclip = subclip.rotate(r)

        # Volume
        if subclip.audio is not None and payload.volume is not None:
            subclip = subclip.volumex(max(0.0, float(payload.volume)))

        # Resize
        if payload.resolution_width and payload.resolution_height:
            subclip = subclip.resize(newsize=(int(payload.resolution_width), int(payload.resolution_height)))

        # Output path
        out_name = f"render_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}.mp4"
        out_path = os.path.join(OUTPUT_DIR, out_name)

        # Write video file
        subclip.write_videofile(out_path, codec="libx264", audio_codec="aac")

        try:
            clip.reader.close()
            if clip.audio:
                clip.audio.reader.close_proc()
            subclip.close()
            clip.close()
        except Exception:
            pass

        output_url = str(request.base_url).rstrip("/") + f"/static/outputs/{out_name}"

        render_doc = {
            "project_id": payload.project_id,
            "asset_id": payload.asset_id,
            "start": start,
            "end": end,
            "speed": payload.speed,
            "volume": payload.volume,
            "rotate": payload.rotate,
            "resolution_width": payload.resolution_width,
            "resolution_height": payload.resolution_height,
            "status": "completed",
            "output_url": output_url,
        }
        render_id = create_document("render", render_doc)

        return {"id": render_id, **render_doc}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
