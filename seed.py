from sqlalchemy.orm import Session
from main import SessionLocal, DBUser, DBAppliance, DBUtilityTariff, get_password_hash

def seed_database():
    db: Session = SessionLocal()
    try:
        # Clear existing data
        db.query(DBAppliance).delete()
        db.query(DBUser).delete()
        db.query(DBUtilityTariff).delete()
        db.commit()

        # Seed Utility Tariff
        tariff = DBUtilityTariff(tier_name="Peak Residential Step-2", rate_per_kwh_pkr=42.0)
        db.add(tariff)

        # Seed Test User
        demo_user = DBUser(
            username="demo_user",
            password_hash=get_password_hash("password123")
        )
        db.add(demo_user)
        db.commit()
        db.refresh(demo_user)

        # Seed 3 Realistic Appliances
        appliances = [
            DBAppliance(user_id=demo_user.id, name="1.5 Ton Inverter AC", wattage=1500.0, daily_hours=8.0),
            DBAppliance(user_id=demo_user.id, name="Water Pump Motor", wattage=1000.0, daily_hours=1.5),
            DBAppliance(user_id=demo_user.id, name="Double Door Refrigerator", wattage=350.0, daily_hours=24.0)
        ]
        db.add_all(appliances)
        db.commit()

        print("Database seeded successfully!")
        print("Demo User Username: demo_user")
        print("Demo User Password: password123")

    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()