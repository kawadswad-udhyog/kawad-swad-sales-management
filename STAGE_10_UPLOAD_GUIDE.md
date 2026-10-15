# Stage 10 upload guide
1. Download and extract this ZIP.
2. Upload the ZIP contents to the existing GitHub repository root, preserving `backend/`, `frontend/`, `docs/`, and other project folders.
3. Replace matching files and commit to `main`.
4. Render should deploy from GitHub if automatic deploy is enabled. Keep environment variables and Secret Files unchanged.
5. Do not commit service-account JSON, tokens, passwords, or environment secrets.
6. Confirm the `SalaryIncentives` tab has the exact documented header row. Review the rules and limitations in `STAGE_10_SALARY_INCENTIVES.md` before payroll use.

The ZIP is prepared from the supplied Stage 9 project files. No claim is made that the live Render deployment was tested.
