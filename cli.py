import argparse
import json
import sys

from sqlalchemy import select

from src.db import Job, JobAuditLog, SessionLocal


def inspect_job(job_id: str) -> None:
    session = SessionLocal()
    try:
        job = session.execute(
            select(Job).where(Job.id == job_id)
        ).scalar_one_or_none()

        if not job:
            print(f"Job {job_id} not found")
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"Job: {job.id}")
        print(f"{'='*60}")
        print(f"  Status:        {job.status.value}")
        print(f"  Analysis Type: {job.analysis_type.value}")
        print(f"  Document URL:  {job.document_url}")
        print(f"  Tokens Used:   {job.tokens_used}")
        print(f"  Created:       {job.created_at}")
        print(f"  Updated:       {job.updated_at}")
        print(f"  Idempotency:   {job.idempotency_key}")

        if job.error:
            print(f"\n  Error: {job.error}")

        if job.result:
            print(f"\n  Result:")
            print(f"  {json.dumps(job.result, indent=2)}")

        audits = session.execute(
            select(JobAuditLog)
            .where(JobAuditLog.job_id == job.id)
            .order_by(JobAuditLog.timestamp)
        ).scalars().all()

        if audits:
            print(f"\n  Audit Trail:")
            for a in audits:
                print(f"    {a.timestamp} | {a.from_status or 'None'} → {a.to_status} | {a.detail or ''}")

        print()
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Document Processing Agent CLI")
    sub = parser.add_subparsers(dest="command")

    inspect = sub.add_parser("inspect-job", help="Inspect a job by ID")
    inspect.add_argument("job_id", help="UUID of the job")

    args = parser.parse_args()

    if args.command == "inspect-job":
        inspect_job(args.job_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
