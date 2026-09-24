import math
import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.db.models import ObjectCatalogue
from app.db.platform import ObjectLocation
from app.db.session import SessionLocal

router = APIRouter(prefix="/geo", tags=["geodata"])

class LocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    geometry: dict | None = None
    wkt: str | None = None

def parse_location(payload: LocationInput):
    if (payload.geometry is None) == (payload.wkt is None):
        raise ValueError("Provide either a GeoJSON Point or WKT POINT")
    if payload.wkt is not None:
        match = re.fullmatch(r"\s*POINT\s*\(\s*([-+\d.eE]+)\s+([-+\d.eE]+)\s*\)\s*", payload.wkt, re.I)
        if not match:
            raise ValueError("Only 2D WKT POINT in EPSG:4326 is supported")
        longitude, latitude = map(float, match.groups())
    else:
        geometry = payload.geometry
        if geometry.get("type") != "Point" or len(geometry.get("coordinates", [])) != 2:
            raise ValueError("Expected a 2D GeoJSON Point")
        longitude, latitude = geometry["coordinates"]
        if isinstance(longitude, bool) or isinstance(latitude, bool):
            raise ValueError("Invalid coordinates")
        longitude, latitude = float(longitude), float(latitude)
    if not (math.isfinite(longitude) and math.isfinite(latitude) and -180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError("Invalid EPSG:4326 coordinates")
    return longitude, latitude

@router.put("/objects/{object_id}")
def update_location(object_id: int, payload: LocationInput):
    try:
        longitude, latitude = parse_location(payload)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from None
    with SessionLocal.begin() as db:
        if not db.get(ObjectCatalogue, object_id):
            raise HTTPException(404, "Object not found")
        db.execute(insert(ObjectLocation).values(object_id=object_id, longitude=longitude, latitude=latitude)
                   .on_conflict_do_update(index_elements=["object_id"], set_={"longitude": longitude, "latitude": latitude}))
    return {"object_id": object_id, "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "wkt": f"POINT ({longitude} {latitude})"}

@router.get("/objects")
def geodata():
    with SessionLocal() as db:
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": row.object_id, "geometry": {"type": "Point", "coordinates": [row.longitude, row.latitude]},
             "properties": {"object_id": row.object_id, "wkt": f"POINT ({row.longitude} {row.latitude})"}}
            for row in db.scalars(select(ObjectLocation).order_by(ObjectLocation.object_id))]}
