"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- Project -> "project"
- Asset -> "asset"
- Render -> "render"
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class Project(BaseModel):
    title: str = Field(..., description="Project title")
    description: Optional[str] = Field(None, description="Project description")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class Asset(BaseModel):
    project_id: str = Field(..., description="Related project id")
    filename: str = Field(..., description="Original filename")
    path: str = Field(..., description="Server path to file")
    url: str = Field(..., description="Public URL to access the file")
    kind: str = Field(..., description="video | audio | image")
    duration: Optional[float] = Field(None, description="Duration in seconds for media that has it")
    width: Optional[int] = None
    height: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class Render(BaseModel):
    project_id: str = Field(...)
    asset_id: str = Field(...)
    start: float = Field(0, ge=0)
    end: Optional[float] = Field(None)
    speed: float = Field(1.0, gt=0)
    volume: float = Field(1.0, ge=0)
    rotate: int = Field(0, description="Rotation degrees: 0,90,180,270")
    resolution_width: Optional[int] = Field(None)
    resolution_height: Optional[int] = Field(None)
    status: str = Field("pending")
    output_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
