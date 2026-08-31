import os
from typing import List, Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from passlib.context import CryptContext
import jwt
from jwt import PyJWTError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables from .env file
load_dotenv()

# --- Configuration & Constants ---
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
DATABASE_URL = "sqlite:///./app.db"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Initialize Gemini Client
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- Database Setup ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Database Models ---
class DBUser(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    
    appliances = relationship("DBAppliance", back_populates="owner")

class DBAppliance(Base):
    __tablename__ = "appliances"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    wattage = Column(Float, nullable=False)
    daily_hours = Column(Float, nullable=False)

    owner = relationship("DBUser", back_populates="appliances")

class DBUtilityTariff(Base):
    __tablename__ = "utility_tariffs"
    id = Column(Integer, primary_key=True, index=True)
    tier_name = Column(String, nullable=False)
    rate_per_kwh_pkr = Column(Float, nullable=False)

Base.metadata.create_all(bind=engine)

# --- Authentication Helpers ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# --- Rate Limiter Setup ---
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Local Electricity Outage & Appliance Cost Optimizer API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- Dependencies ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> DBUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except PyJWTError:
        raise credentials_exception
        
    user = db.query(DBUser).filter(DBUser.username == username).first()
    if user is None:
        raise credentials_exception
    return user

# --- Pydantic Schemas ---
class UserRegister(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)

class Token(BaseModel):
    access_token: str
    token_type: str

class ApplianceCreate(BaseModel):
    name: str = Field(..., example="1.5 Ton Inverter AC")
    wattage: float = Field(..., gt=0, example=1800)
    daily_hours: float = Field(..., ge=0, le=24, example=8)

class ApplianceOut(BaseModel):
    id: int
    name: str
    wattage: float
    daily_hours: float

    class Config:
        from_attributes = True

class CostEstimateOut(BaseModel):
    total_appliances: int
    daily_outage_hours: float
    monthly_kwh_consumed: float
    applied_tariff_rate_pkr: float
    total_monthly_cost_pkr: float

class AIOptimizeRequest(BaseModel):
    daily_outage_hours: float = Field(..., ge=0, le=24, example=4)

class AIOptimizeResponse(BaseModel):
    monthly_cost_pkr: float
    ai_recommendations: str

# --- Endpoints ---

@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    existing_user = db.query(DBUser).filter(DBUser.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_pwd = get_password_hash(user_data.password)
    new_user = DBUser(username=user_data.username, password_hash=hashed_pwd)
    db.add(new_user)
    db.commit()
    return {"message": "User registered successfully"}

@app.post("/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(DBUser).filter(DBUser.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/appliances", response_model=ApplianceOut, status_code=status.HTTP_201_CREATED)
def add_appliance(
    appliance: ApplianceCreate,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_appliance = DBAppliance(
        user_id=current_user.id,
        name=appliance.name,
        wattage=appliance.wattage,
        daily_hours=appliance.daily_hours
    )
    db.add(db_appliance)
    db.commit()
    db.refresh(db_appliance)
    return db_appliance

@app.get("/appliances", response_model=List[ApplianceOut])
def list_appliances(
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(DBAppliance).filter(DBAppliance.user_id == current_user.id).all()

@app.get("/cost-estimate", response_model=CostEstimateOut)
def calculate_cost_estimate(
    daily_outage_hours: float = 0.0,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    appliances = db.query(DBAppliance).filter(DBAppliance.user_id == current_user.id).all()
    
    # Get active electricity tariff rate (defaulting to latest tier or base 38.5 PKR)
    tariff = db.query(DBUtilityTariff).first()
    rate_pkr = tariff.rate_per_kwh_pkr if tariff else 38.5

    total_monthly_kwh = 0.0
    for item in appliances:
        # Adjust daily operating hours based on outage load shedding hours
        effective_hours = max(0.0, item.daily_hours - daily_outage_hours)
        monthly_kwh = (item.wattage * effective_hours * 30) / 1000.0
        total_monthly_kwh += monthly_kwh

    total_cost_pkr = total_monthly_kwh * rate_pkr

    return CostEstimateOut(
        total_appliances=len(appliances),
        daily_outage_hours=daily_outage_hours,
        monthly_kwh_consumed=round(total_monthly_kwh, 2),
        applied_tariff_rate_pkr=rate_pkr,
        total_monthly_cost_pkr=round(total_cost_pkr, 2)
    )

@app.post("/ai-optimize-savings", response_model=AIOptimizeResponse)
@limiter.limit("5/minute")
def ai_optimize_savings(
    request: Request,
    body: AIOptimizeRequest,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Force reload of environment variables in case .env was updated
    load_dotenv(override=True)
    active_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not active_key or active_key == "your_free_google_gemini_api_key_here":
        raise HTTPException(
            status_code=500, 
            detail="GEMINI_API_KEY is missing or set to placeholder in .env"
        )

    # Configure Gemini with the fresh key
    genai.configure(api_key=active_key)

    # Calculate user's current consumption profile
    appliances = db.query(DBAppliance).filter(DBAppliance.user_id == current_user.id).all()
    tariff = db.query(DBUtilityTariff).first()
    rate_pkr = tariff.rate_per_kwh_pkr if tariff else 38.5

    if not appliances:
        raise HTTPException(status_code=400, detail="No appliances found for this user.")

    appliance_details = []
    total_monthly_kwh = 0.0
    for app in appliances:
        effective_hours = max(0.0, app.daily_hours - body.daily_outage_hours)
        monthly_kwh = (app.wattage * effective_hours * 30) / 1000.0
        total_monthly_kwh += monthly_kwh
        appliance_details.append(f"- {app.name}: {app.wattage}W, running {effective_hours} hrs/day")

    total_cost_pkr = round(total_monthly_kwh * rate_pkr, 2)

    prompt = f"""
    You are an expert energy-saving advisor for households in Pakistan dealing with power outages (load shedding) and high tariffs.
    
    User Profile:
    - Daily Load-Shedding / Outage Duration: {body.daily_outage_hours} hours/day
    - Electricity Rate: {rate_pkr} PKR/kWh
    - Total Monthly Estimated Bill: {total_cost_pkr} PKR
    - User's Appliances:
    {chr(10).join(appliance_details)}

    Task:
    Provide exactly 3 short, hyper-practical action items to help this user reduce their electricity bill during peak hours and adapt to their power outage schedule. Keep it concise.
    """

    try:
        model = genai.GenerativeModel("gemini-3.6-flash")
        response = model.generate_content(prompt)
        ai_text = response.text if response.text else "Could not generate suggestions."
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini API Error: {str(e)}")

    return AIOptimizeResponse(
        monthly_cost_pkr=total_cost_pkr,
        ai_recommendations=ai_text
    )