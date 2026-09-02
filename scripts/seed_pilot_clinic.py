"""Set up a clean clinic for a real Phase-10 pilot, entirely through the real API --
never raw SQL against the database. This creates a NEW clinic namespace; it never
deletes or truncates anything, so it's safe to run against a shared/demo database
without touching existing clinics' data.

Usage:
    python scripts/seed_pilot_clinic.py \\
        --clinic-name "Sharma Clinic" \\
        --admin-name "Dr. Sharma" --admin-contact admin@sharmaclinic.pilot --admin-password <choose one> \\
        --doctor-name "Dr. Sharma" --doctor-contact doctor@sharmaclinic.pilot --doctor-password <choose one> \\
        --receptionist-name "Priya" --receptionist-contact reception@sharmaclinic.pilot --receptionist-password <choose one>

Run with --base-url to target somewhere other than a local docker-compose instance
(default: http://localhost:8000).
"""
import argparse
import sys

import requests


def _post(base_url: str, path: str, json: dict, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = requests.post(f"{base_url}{path}", json=json, headers=headers)
    if not resp.ok:
        print(f"FAILED {path}: {resp.status_code} {resp.text}", file=sys.stderr)
        resp.raise_for_status()
    return resp.json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--clinic-name", required=True)
    parser.add_argument("--admin-name", required=True)
    parser.add_argument("--admin-contact", required=True)
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--doctor-name", required=True)
    parser.add_argument("--doctor-contact", required=True)
    parser.add_argument("--doctor-password", required=True)
    parser.add_argument("--receptionist-name", default=None)
    parser.add_argument("--receptionist-contact", default=None)
    parser.add_argument("--receptionist-password", default=None)
    args = parser.parse_args()

    print(f"Creating clinic '{args.clinic_name}' at {args.base_url} ...")
    signup = _post(args.base_url, "/staff/signup", {
        "clinic_name": args.clinic_name,
        "admin_name": args.admin_name,
        "admin_contact": args.admin_contact,
        "admin_password": args.admin_password,
    })
    clinic_id = signup["clinic_id"]
    admin_token = signup["access_token"]
    print(f"  clinic_id: {clinic_id}")

    print("Adding doctor account ...")
    _post(args.base_url, "/admin/staff", {
        "name": args.doctor_name, "role": "doctor",
        "contact": args.doctor_contact, "password": args.doctor_password,
    }, token=admin_token)

    if args.receptionist_contact:
        print("Adding receptionist account ...")
        _post(args.base_url, "/admin/staff", {
            "name": args.receptionist_name, "role": "receptionist",
            "contact": args.receptionist_contact, "password": args.receptionist_password,
        }, token=admin_token)

    patient_link = f"{args.base_url}/patient-app/?clinic={clinic_id}"

    print("\n" + "=" * 60)
    print("PILOT CLINIC READY")
    print("=" * 60)
    print(f"Clinic ID:      {clinic_id}")
    print(f"Dashboard:      {args.base_url}/dashboard/")
    print(f"Patient link:   {patient_link}")
    print("\nLogins:")
    print(f"  admin        {args.admin_contact} / (the password you set)")
    print(f"  doctor       {args.doctor_contact} / (the password you set)")
    if args.receptionist_contact:
        print(f"  receptionist {args.receptionist_contact} / (the password you set)")
    print("\nFees default to standard=Rs500 / priority=Rs800 / emergency=Rs1200 --")
    print("edit them from the dashboard's Fees card (any staff role can) before opening.")
    print("=" * 60)


if __name__ == "__main__":
    main()
