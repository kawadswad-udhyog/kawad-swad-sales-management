# Production Module Code Update Notes

This package adds the first production-management stage to the current app.

## Added
- `backend/app/routers/production.py`: authenticated APIs for worker profiles, attendance/wage accrual, recipe versions, daily production approval, packaging, stock summary, and dispatch.
- `src/views/ProductionView.tsx`: Production & Factory screen.
- Navigation and app route for Owner/PA access.
- New Sheets tabs are created on first write where possible.
- `backend/tests/test_production_module.py`: basic production, recipe-consumption, packaging SKU mapping, and dispatch checks.
- `PRODUCTION_MODULE_GUIDE.md`: setup and operations notes.

## Verification run in this environment
- Python compilation: passed.
- Production module + buyer-info backend tests: 14 passed.
- Full existing backend test suite is not fully green in this environment: some existing tests fail due to the installed Pydantic/FastAPI test environment assumptions (validation errors raised at model construction, and an existing APIRouter `.patch` test collection issue). These were not caused by the production module.
- Frontend TypeScript/Vite build: not run because npm dependencies are not installed and dependency installation is not available/verified here.
- Live Google Sheets/Render integration: not tested.

## Before deployment
1. Upload the full repository contents to GitHub, keeping folder structure.
2. Ensure `RawMaterials` contains opening stock and compatible units for every ingredient in the recipe.
3. Ensure each variant has active 200 g, 500 g, and 1000 g SKU rows, with the same exact `product_name` across sizes.
4. Deploy to the development Render services first and verify worker attendance, recipe material deduction, production approval, packaging, and channel dispatch using test records.
5. Do not treat the module as production-ready until the frontend build and live Sheets integration have passed verification.
