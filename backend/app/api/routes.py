from fastapi import APIRouter

router = APIRouter(prefix="/api")

@router.get("/status")
def status():
    return {
        "status": "ok",
        "service": "social-automation-api",
        "version": "0.1.0"
    }

@router.get("/tenants")
def tenants():
    return {"items": [], "message": "Tenant API foundation ready"}

@router.get("/social/accounts")
def social_accounts():
    return {"items": [], "message": "Social connector foundation ready"}

@router.get("/posts")
def posts():
    return {"items": [], "message": "Post API foundation ready"}

@router.get("/campaigns")
def campaigns():
    return {"items": [], "message": "Campaign API foundation ready"}
