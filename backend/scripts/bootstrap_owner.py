"""One-time local utility to create the first Owner account in AuthUsers."""
import getpass, os
from app.store import Store, now
from app.security import hash_password

def main():
    if os.getenv("SALES_GOOGLE_SPREADSHEET_ID") is None or os.getenv("SALES_GOOGLE_SERVICE_ACCOUNT_FILE") is None:
        raise SystemExit("Set SALES_GOOGLE_SPREADSHEET_ID and SALES_GOOGLE_SERVICE_ACCOUNT_FILE first.")
    s=Store()
    username=input("Owner username: ").strip()
    full_name=input("Owner full name: ").strip() or "Owner"
    password=getpass.getpass("Owner password (minimum 12 characters): ")
    if len(password)<12: raise SystemExit("Password must be at least 12 characters.")
    if any(str(x.get("username","")).lower()==username.lower() for x in s.auth_rows()): raise SystemExit("Username already exists.")
    user_id="USR-OWNER-001"
    stamp=now()
    if not any(str(x.get("user_id"))==user_id for x in s.rows("Users")):
        s.append("Users",{"user_id":user_id,"full_name":full_name,"role":"OWNER","mobile":"","email":"","active":"TRUE","created_at":stamp,"notes":"Initial owner"})
    s.append_auth({"auth_id":"AUTH-OWNER-001","user_id":user_id,"username":username,"password_hash":hash_password(password),"role":"OWNER","active":"TRUE","created_at":stamp,"must_change_password":"FALSE"})
    print("Owner account created. Sign in and create PA and SALESMAN users through POST /api/users.")
if __name__=="__main__": main()
