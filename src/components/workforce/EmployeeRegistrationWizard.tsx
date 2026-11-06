import React, { useState, useMemo } from 'react';
import {
  Users,
  Briefcase,
  UserCheck,
  Coins,
  KeyRound,
  FileCheck,
  CheckCircle2,
  ChevronRight,
  ChevronLeft,
  X,
  Building,
  Phone,
  ShieldCheck,
  Plus,
  AlertCircle,
} from 'lucide-react';
import {
  FormLayout,
  FormSection,
  FormField,
  TextInput,
  SelectInput,
  MoneyInput,
  DateInput,
  TextArea,
  CalculationPreview,
} from '../common/FormComponents';
import {
  EmployeeCategory,
  DESIGNATIONS,
  getCategoryTitle,
} from '../../utils/permissions';
import { User, UserRole } from '../../types';

interface EmployeeRegistrationWizardProps {
  existingUsers: User[];
  onClose: () => void;
  onSubmit: (employeeData: any) => Promise<boolean>;
  isOwner?: boolean;
}

export const EmployeeRegistrationWizard: React.FC<EmployeeRegistrationWizardProps> = ({
  existingUsers,
  onClose,
  onSubmit,
  isOwner = true,
}) => {
  const [currentStep, setCurrentStep] = useState<number>(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [createdSummary, setCreatedSummary] = useState<any>(null);

  // Form State
  // Step 1: Category & Designation
  const [category, setCategory] = useState<EmployeeCategory>('FACTORY_WORKERS');
  const [selectedDesignationId, setSelectedDesignationId] = useState<string>('production_worker');
  const [customDesignation, setCustomDesignation] = useState('');

  // Step 2: Basic Info
  const [fullName, setFullName] = useState('');
  const [mobile, setMobile] = useState('');
  const [emergencyContact, setEmergencyContact] = useState('');
  const [address, setAddress] = useState('');

  // Step 3: Department & Reporting
  const [department, setDepartment] = useState('Factory Floor');
  const [joiningDate, setJoiningDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [reportingManagerId, setReportingManagerId] = useState('');

  // Step 4: Salary & Wages
  const [wageType, setWageType] = useState<'MONTHLY' | 'DAILY' | 'PIECE_RATE'>('MONTHLY');
  const [baseSalary, setBaseSalary] = useState<number>(18000);
  const [bankAccount, setBankAccount] = useState('');
  const [bankIfsc, setBankIfsc] = useState('');

  // Step 5: System Access & Login
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('Kawad@1234');
  const [systemRole, setSystemRole] = useState<UserRole>('FACTORY_WORKER');
  const [isActive, setIsActive] = useState(true);

  // Filtered designations based on category
  const categoryDesignations = useMemo(() => {
    return Object.values(DESIGNATIONS).filter((d) => d.category === category);
  }, [category]);

  // When category changes, reset designation and default department
  const handleCategoryChange = (newCat: EmployeeCategory) => {
    setCategory(newCat);
    const available = Object.values(DESIGNATIONS).filter((d) => d.category === newCat);
    if (available.length > 0) {
      setSelectedDesignationId(available[0].id);
      setDepartment(available[0].department);
      setSystemRole(available[0].defaultRole);
    }
    if (newCat === 'FACTORY_WORKERS') {
      setWageType('DAILY');
      setBaseSalary(500);
    } else if (newCat === 'FIELD_STAFF') {
      setWageType('MONTHLY');
      setBaseSalary(16000);
    } else {
      setWageType('MONTHLY');
      setBaseSalary(22000);
    }
  };

  const handleDesignationSelect = (desigId: string) => {
    setSelectedDesignationId(desigId);
    const found = DESIGNATIONS[desigId];
    if (found) {
      setDepartment(found.department);
      setSystemRole(found.defaultRole);
    }
  };

  // Auto-generate username from full name if blank
  const handleFullNameChange = (val: string) => {
    setFullName(val);
    if (!username || username === fullName.toLowerCase().replace(/[^a-z0-9]/g, '')) {
      const suggested = val
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]/g, '');
      setUsername(suggested);
    }
  };

  // Potential managers list
  const potentialManagers = useMemo(() => {
    return existingUsers.filter((u) => {
      const r = String(u.role || '').toUpperCase();
      return ['OWNER', 'OWNER_ADMIN', 'ADMIN', 'PA', 'MANAGER', 'LABOUR_SUPERVISOR'].includes(r);
    });
  }, [existingUsers]);

  // Effective designation label
  const resolvedDesignationTitle =
    selectedDesignationId === 'custom'
      ? customDesignation.trim() || 'Staff Specialist'
      : DESIGNATIONS[selectedDesignationId]?.title || selectedDesignationId;

  // Step Validation
  const validateStep = (step: number): boolean => {
    setErrorMsg('');
    if (step === 1) {
      if (selectedDesignationId === 'custom' && !customDesignation.trim()) {
        setErrorMsg('Please specify the custom designation.');
        return false;
      }
      return true;
    }
    if (step === 2) {
      if (!fullName.trim()) {
        setErrorMsg('Full Name is required.');
        return false;
      }
      if (mobile && !/^\d{10}$/.test(mobile.replace(/\D/g, ''))) {
        setErrorMsg('Please enter a valid 10-digit mobile number.');
        return false;
      }
      return true;
    }
    if (step === 3) {
      if (!department.trim()) {
        setErrorMsg('Department is required.');
        return false;
      }
      return true;
    }
    if (step === 4) {
      if (!baseSalary || baseSalary <= 0) {
        setErrorMsg('Please enter a valid wage or salary amount greater than zero.');
        return false;
      }
      return true;
    }
    if (step === 5) {
      const cleanUser = username.trim().toLowerCase();
      if (!cleanUser || cleanUser.length < 3) {
        setErrorMsg('Username must be at least 3 characters long.');
        return false;
      }
      const isTaken = existingUsers.some((u) => u.username.toLowerCase() === cleanUser);
      if (isTaken) {
        setErrorMsg(`Username "${cleanUser}" is already taken. Please choose another.`);
        return false;
      }
      if (!password || password.length < 8) {
        setErrorMsg('Initial password must be at least 8 characters long.');
        return false;
      }
      return true;
    }
    return true;
  };

  const handleNext = () => {
    if (validateStep(currentStep)) {
      setCurrentStep((prev) => prev + 1);
    }
  };

  const handleBack = () => {
    setErrorMsg('');
    setCurrentStep((prev) => Math.max(1, prev - 1));
  };

  const handleFinalSubmit = async () => {
    if (!validateStep(5)) {
      setCurrentStep(5);
      return;
    }

    setIsSubmitting(true);
    setErrorMsg('');

    const payload = {
      full_name: fullName.trim(),
      username: username.trim().toLowerCase(),
      password,
      role: systemRole,
      mobile: mobile.trim(),
      email: `${username.trim().toLowerCase()}@kawadswad.com`,
      employment_type: category === 'FACTORY_WORKERS' ? 'Factory Worker' : 'Salaried Employee',
      designation: resolvedDesignationTitle,
      department: department.trim(),
      reporting_manager_id: reportingManagerId || undefined,
      joining_date: joiningDate,
      employment_status: isActive ? 'ACTIVE' : 'INACTIVE',
      salary_frequency: wageType === 'DAILY' ? 'DAILY' : 'MONTHLY',
      basic_salary: Number(baseSalary),
      address: address.trim(),
      emergency_contact: emergencyContact.trim(),
      bank_details: bankAccount ? `A/C: ${bankAccount} | IFSC: ${bankIfsc}` : undefined,
      active: isActive,
      notes: `Registered via 7-Step Staff Wizard (${getCategoryTitle(category)})`,
    };

    try {
      const success = await onSubmit(payload);
      if (success) {
        setCreatedSummary({
          fullName: payload.full_name,
          username: payload.username,
          category: getCategoryTitle(category),
          designation: resolvedDesignationTitle,
          role: systemRole,
          department: payload.department,
          salaryText:
            wageType === 'DAILY'
              ? `₹${Number(baseSalary).toLocaleString('en-IN')} / Day`
              : `₹${Number(baseSalary).toLocaleString('en-IN')} / Month`,
        });
        setCurrentStep(7);
      } else {
        setErrorMsg('Registration could not be completed. Please check server connectivity.');
      }
    } catch (err: any) {
      setErrorMsg(err?.message || 'Error occurred while saving employee record.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Steps definition for top progress tracker
  const STEPS = [
    { num: 1, label: 'Category', icon: <Briefcase size={14} /> },
    { num: 2, label: 'Basic Info', icon: <Users size={14} /> },
    { num: 3, label: 'Department', icon: <Building size={14} /> },
    { num: 4, label: 'Salary', icon: <Coins size={14} /> },
    { num: 5, label: 'Access', icon: <KeyRound size={14} /> },
    { num: 6, label: 'Review', icon: <FileCheck size={14} /> },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-slate-900/60 backdrop-blur-xs overflow-y-auto">
      <div className="w-full max-w-2xl bg-white rounded-3xl shadow-2xl border border-slate-200 overflow-hidden my-auto flex flex-col max-h-[92vh]">
        {/* Wizard Header */}
        <div className="px-6 py-4 border-b border-slate-200 bg-slate-50/80 flex items-center justify-between shrink-0">
          <div>
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-lg bg-emerald-800 text-white flex items-center justify-center text-xs font-bold">
                7
              </span>
              <h2 className="text-base font-bold text-slate-900 m-0">
                Register New Team Member
              </h2>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Step {Math.min(currentStep, 6)} of 6: Guided staff onboarding
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 rounded-xl transition-colors cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Step Indicator Bar (Hidden on Success Step 7) */}
        {currentStep <= 6 && (
          <div className="px-6 py-2.5 bg-slate-100/70 border-b border-slate-200 flex items-center justify-between gap-1 overflow-x-auto shrink-0">
            {STEPS.map((s) => {
              const isPast = currentStep > s.num;
              const isCurrent = currentStep === s.num;
              return (
                <div
                  key={s.num}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-semibold whitespace-nowrap transition-colors ${
                    isCurrent
                      ? 'bg-emerald-800 text-white shadow-2xs'
                      : isPast
                      ? 'bg-emerald-100 text-emerald-900'
                      : 'text-slate-400'
                  }`}
                >
                  {isPast ? <CheckCircle2 size={13} className="text-emerald-700" /> : s.icon}
                  <span>{s.label}</span>
                </div>
              );
            })}
          </div>
        )}

        {/* Error Alert */}
        {errorMsg && (
          <div className="mx-6 mt-4 p-3 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs flex items-center gap-2">
            <AlertCircle size={16} className="text-red-600 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Step Body */}
        <div className="p-6 overflow-y-auto flex-1 text-slate-800">
          {/* STEP 1: CATEGORY & DESIGNATION */}
          {currentStep === 1 && (
            <div className="space-y-5">
              <div>
                <h3 className="text-sm font-bold text-slate-900 mb-1">
                  1. Select Work Category
                </h3>
                <p className="text-xs text-slate-500 mb-3">
                  This determines the worker's daily workspace and simplified interface.
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {[
                    {
                      id: 'FACTORY_WORKERS' as EmployeeCategory,
                      title: 'Factory Worker',
                      subtitle: 'Production, packing & plant operations',
                      badge: 'Factory Floor',
                      bgClass: 'hover:border-amber-400',
                      activeClass: 'border-amber-600 bg-amber-50/50 ring-2 ring-amber-500',
                    },
                    {
                      id: 'OFFICE_STAFF' as EmployeeCategory,
                      title: 'Office Staff',
                      subtitle: 'Billing, accounts, purchasing & admin',
                      badge: 'Office Desk',
                      bgClass: 'hover:border-emerald-400',
                      activeClass: 'border-emerald-700 bg-emerald-50/50 ring-2 ring-emerald-600',
                    },
                    {
                      id: 'FIELD_STAFF' as EmployeeCategory,
                      title: 'Field Staff',
                      subtitle: 'Store visits, sales orders & cash collection',
                      badge: 'Field & Sales',
                      bgClass: 'hover:border-blue-400',
                      activeClass: 'border-blue-600 bg-blue-50/50 ring-2 ring-blue-500',
                    },
                  ].map((cat) => (
                    <button
                      key={cat.id}
                      type="button"
                      onClick={() => handleCategoryChange(cat.id)}
                      className={`p-3.5 rounded-2xl border text-left transition-all cursor-pointer ${
                        category === cat.id
                          ? cat.activeClass
                          : `border-slate-200 bg-white ${cat.bgClass}`
                      }`}
                    >
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-white border border-slate-200 text-slate-600">
                        {cat.badge}
                      </span>
                      <div className="text-sm font-bold text-slate-900 mt-2">{cat.title}</div>
                      <div className="text-[11px] text-slate-500 mt-0.5">{cat.subtitle}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <h3 className="text-sm font-bold text-slate-900 mb-1">
                  2. Select Job Role (Designation)
                </h3>
                <p className="text-xs text-slate-500 mb-3">
                  Choose a standard role or enter a custom title.
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                  {categoryDesignations.map((d) => (
                    <button
                      key={d.id}
                      type="button"
                      onClick={() => handleDesignationSelect(d.id)}
                      className={`p-3 rounded-xl border text-left transition-all cursor-pointer flex items-center justify-between ${
                        selectedDesignationId === d.id
                          ? 'border-emerald-800 bg-emerald-50 text-emerald-950 font-bold ring-1 ring-emerald-800'
                          : 'border-slate-200 bg-white hover:bg-slate-50 text-slate-700'
                      }`}
                    >
                      <div>
                        <div className="text-xs font-bold">{d.title}</div>
                        <div className="text-[10px] text-slate-400 font-normal">{d.department}</div>
                      </div>
                      {selectedDesignationId === d.id && (
                        <CheckCircle2 size={16} className="text-emerald-700 shrink-0" />
                      )}
                    </button>
                  ))}

                  <button
                    type="button"
                    onClick={() => setSelectedDesignationId('custom')}
                    className={`p-3 rounded-xl border text-left transition-all cursor-pointer flex items-center justify-between ${
                      selectedDesignationId === 'custom'
                        ? 'border-emerald-800 bg-emerald-50 text-emerald-950 font-bold ring-1 ring-emerald-800'
                        : 'border-slate-200 bg-white hover:bg-slate-50 text-slate-700'
                    }`}
                  >
                    <div>
                      <div className="text-xs font-bold">+ Custom Designation</div>
                      <div className="text-[10px] text-slate-400 font-normal">Define unique role</div>
                    </div>
                  </button>
                </div>

                {selectedDesignationId === 'custom' && (
                  <div className="mt-3">
                    <FormField label="Enter Custom Designation Title" required>
                      <TextInput
                        value={customDesignation}
                        onChange={(e) => setCustomDesignation(e.target.value)}
                        placeholder="e.g. Master Roaster, Inventory Lead"
                      />
                    </FormField>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* STEP 2: BASIC INFORMATION */}
          {currentStep === 2 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-bold text-slate-900 mb-1">
                  Personal & Contact Details
                </h3>
                <p className="text-xs text-slate-500 mb-3">
                  Essential identification records for payroll and emergency contact.
                </p>
              </div>

              <FormField label="Full Name" required helpText="Legal name as per Aadhaar/Bank">
                <TextInput
                  value={fullName}
                  onChange={(e) => handleFullNameChange(e.target.value)}
                  placeholder="e.g. Ramesh Kumar Verma"
                />
              </FormField>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="Mobile Number" helpText="10-digit primary phone">
                  <TextInput
                    value={mobile}
                    onChange={(e) => setMobile(e.target.value)}
                    placeholder="9876543210"
                    type="tel"
                  />
                </FormField>

                <FormField label="Emergency Contact" helpText="Family member or relative phone">
                  <TextInput
                    value={emergencyContact}
                    onChange={(e) => setEmergencyContact(e.target.value)}
                    placeholder="9876500000 (Father / Spouse)"
                  />
                </FormField>
              </div>

              <FormField label="Residential Address" helpText="Local city or village address">
                <TextArea
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="e.g. Village Kawad, Post Dhoraji, Rajkot Dist, Gujarat"
                  rows={2}
                />
              </FormField>
            </div>
          )}

          {/* STEP 3: DEPARTMENT & REPORTING */}
          {currentStep === 3 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-bold text-slate-900 mb-1">
                  Department & Reporting Line
                </h3>
                <p className="text-xs text-slate-500 mb-3">
                  Assign the employee's physical work location and reporting manager.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="Department" required>
                  <SelectInput
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                    options={[
                      { value: 'Factory Floor', label: 'Factory Floor' },
                      { value: 'Packaging', label: 'Packaging' },
                      { value: 'Milling & Roasting', label: 'Milling & Roasting' },
                      { value: 'Field Sales', label: 'Field Sales' },
                      { value: 'Sales & Billing', label: 'Sales & Billing' },
                      { value: 'Raw Material Supply', label: 'Raw Material Supply' },
                      { value: 'Warehouse & Inventory', label: 'Warehouse & Inventory' },
                      { value: 'Accounts & Finance', label: 'Accounts & Finance' },
                      { value: 'Administration', label: 'Administration' },
                      { value: 'Quality Control', label: 'Quality Control' },
                    ]}
                  />
                </FormField>

                <FormField label="Date of Joining" required>
                  <DateInput value={joiningDate} onChange={setJoiningDate} />
                </FormField>
              </div>

              <FormField label="Reporting Manager" helpText="Select manager who oversees their work">
                <SelectInput
                  value={reportingManagerId}
                  onChange={(e) => setReportingManagerId(e.target.value)}
                  options={[
                    { value: '', label: '-- Direct to Business Owner --' },
                    ...potentialManagers.map((m) => ({
                      value: m.user_id,
                      label: `${m.full_name || m.username} (${m.role})`,
                    })),
                  ]}
                />
              </FormField>

              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-xs text-slate-600 flex items-center gap-2">
                <ShieldCheck size={16} className="text-emerald-700 shrink-0" />
                <span>
                  The reporting manager will receive attendance logs and operational submissions
                  from this employee.
                </span>
              </div>
            </div>
          )}

          {/* STEP 4: SALARY & WAGES */}
          {currentStep === 4 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-bold text-slate-900 mb-1">
                  Salary & Wage Structure
                </h3>
                <p className="text-xs text-slate-500 mb-3">
                  Configure pay frequency and payment details for monthly slips.
                </p>
              </div>

              <FormField label="Wage Type / Pay Frequency" required>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { id: 'MONTHLY' as const, label: 'Monthly Fixed' },
                    { id: 'DAILY' as const, label: 'Daily Wage' },
                    { id: 'PIECE_RATE' as const, label: 'Piece-Rate' },
                  ].map((w) => (
                    <button
                      key={w.id}
                      type="button"
                      onClick={() => setWageType(w.id)}
                      className={`p-2.5 rounded-xl border text-xs font-bold transition-all cursor-pointer text-center ${
                        wageType === w.id
                          ? 'border-emerald-800 bg-emerald-50 text-emerald-950 ring-1 ring-emerald-800'
                          : 'border-slate-200 bg-white hover:bg-slate-50 text-slate-700'
                      }`}
                    >
                      {w.label}
                    </button>
                  ))}
                </div>
              </FormField>

              <FormField
                label={
                  wageType === 'DAILY'
                    ? 'Daily Wage Rate (₹ / Day)'
                    : wageType === 'PIECE_RATE'
                    ? 'Piece Rate (₹ / Packet or Kg)'
                    : 'Basic Monthly Salary (₹ / Month)'
                }
                required
              >
                <MoneyInput
                  value={baseSalary}
                  onChange={(v) => setBaseSalary(v)}
                  placeholder={wageType === 'DAILY' ? '500' : '18000'}
                />
              </FormField>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="Bank Account Number" helpText="Optional for direct bank payout">
                  <TextInput
                    value={bankAccount}
                    onChange={(e) => setBankAccount(e.target.value)}
                    placeholder="e.g. 5010045612348"
                  />
                </FormField>

                <FormField label="Bank IFSC Code" helpText="11-character code">
                  <TextInput
                    value={bankIfsc}
                    onChange={(e) => setBankIfsc(e.target.value)}
                    placeholder="e.g. HDFC0000123"
                  />
                </FormField>
              </div>

              <CalculationPreview
                items={[
                  {
                    label: 'Base Rate',
                    value: `₹${Number(baseSalary).toLocaleString('en-IN')}`,
                  },
                  {
                    label:
                      wageType === 'DAILY'
                        ? 'Est. Monthly (26 Days)'
                        : 'Monthly Standard',
                    value: `₹${(wageType === 'DAILY' ? baseSalary * 26 : baseSalary).toLocaleString('en-IN')}`,
                    isHighlight: true,
                    variant: 'emerald',
                  },
                ]}
                title="Compensation Summary"
              />
            </div>
          )}

          {/* STEP 5: SYSTEM ACCESS & LOGIN */}
          {currentStep === 5 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-bold text-slate-900 mb-1">
                  System Login & Permissions
                </h3>
                <p className="text-xs text-slate-500 mb-3">
                  Credentials for accessing Kawad Swad ERP.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="Username" required helpText="Used to sign in">
                  <TextInput
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="e.g. ramesh.verma"
                  />
                </FormField>

                <FormField label="Initial Password" required helpText="Min 8 characters">
                  <TextInput
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Enter secure password"
                    type="text"
                  />
                </FormField>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="System Role" required helpText="Controls backend authorization">
                  <SelectInput
                    value={systemRole}
                    onChange={(e) => setSystemRole(e.target.value as UserRole)}
                    options={[
                      { value: 'FACTORY_WORKER', label: 'FACTORY_WORKER (Factory Work)' },
                      { value: 'OPERATOR', label: 'OPERATOR (Milling / Roaster)' },
                      { value: 'LABOUR_SUPERVISOR', label: 'LABOUR_SUPERVISOR (Supervisor)' },
                      { value: 'SALESMAN', label: 'SALESMAN (Field Sales)' },
                      { value: 'EMPLOYEE', label: 'EMPLOYEE (Office Staff)' },
                      { value: 'PA', label: 'PA (Personal Assistant / Billing)' },
                      { value: 'MANAGER', label: 'MANAGER (Operations Manager)' },
                      { value: 'ACCOUNTANT', label: 'ACCOUNTANT (Finance)' },
                    ]}
                  />
                </FormField>

                <FormField label="Account Status" required>
                  <div className="flex items-center gap-2 mt-2">
                    <button
                      type="button"
                      onClick={() => setIsActive(!isActive)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors cursor-pointer ${
                        isActive ? 'bg-emerald-600' : 'bg-slate-300'
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                          isActive ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                    <span className="text-xs font-bold text-slate-700">
                      {isActive ? 'Active (Permitted to Login)' : 'Inactive'}
                    </span>
                  </div>
                </FormField>
              </div>
            </div>
          )}

          {/* STEP 6: REVIEW & CONFIRM */}
          {currentStep === 6 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-bold text-slate-900 mb-1">
                  Review & Confirm Details
                </h3>
                <p className="text-xs text-slate-500 mb-3">
                  Verify the information before saving to the employee directory.
                </p>
              </div>

              <div className="bg-slate-50 rounded-2xl p-4 border border-slate-200 divide-y divide-slate-200 text-xs space-y-2">
                <div className="pb-2 flex justify-between items-center">
                  <div>
                    <span className="text-[10px] uppercase font-bold text-slate-400">Category & Role</span>
                    <div className="text-sm font-bold text-slate-900 mt-0.5">
                      {fullName || 'No name provided'}
                    </div>
                    <div className="text-xs text-emerald-800 font-semibold">
                      {resolvedDesignationTitle} · {getCategoryTitle(category)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setCurrentStep(1)}
                    className="text-xs text-emerald-700 hover:underline font-bold"
                  >
                    Edit
                  </button>
                </div>

                <div className="py-2 grid grid-cols-2 gap-2">
                  <div>
                    <span className="text-slate-500 font-medium">Department:</span>
                    <div className="font-bold text-slate-800">{department}</div>
                  </div>
                  <div>
                    <span className="text-slate-500 font-medium">Joining Date:</span>
                    <div className="font-bold text-slate-800">{joiningDate}</div>
                  </div>
                  <div>
                    <span className="text-slate-500 font-medium">Contact:</span>
                    <div className="font-bold text-slate-800">{mobile || '--'}</div>
                  </div>
                  <div>
                    <span className="text-slate-500 font-medium">Pay Rate:</span>
                    <div className="font-bold text-emerald-800">
                      ₹{Number(baseSalary).toLocaleString('en-IN')}{' '}
                      {wageType === 'DAILY' ? '/ Day' : '/ Month'}
                    </div>
                  </div>
                </div>

                <div className="pt-2 flex justify-between items-center">
                  <div>
                    <span className="text-slate-500 font-medium">Login Username:</span>
                    <div className="font-mono font-bold text-slate-900">@{username}</div>
                  </div>
                  <div>
                    <span className="text-slate-500 font-medium">System Role:</span>
                    <div className="font-bold text-emerald-800">{systemRole}</div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* STEP 7: SUCCESS & SUMMARY */}
          {currentStep === 7 && createdSummary && (
            <div className="text-center py-6 space-y-4">
              <div className="w-16 h-16 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center mx-auto">
                <CheckCircle2 size={36} />
              </div>

              <div>
                <h3 className="text-lg font-black text-slate-900 m-0">
                  Staff Successfully Registered!
                </h3>
                <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto">
                  {createdSummary.fullName} is now registered in Kawad Swad ERP. Their workspace and
                  credentials are ready for use.
                </p>
              </div>

              <div className="bg-slate-50 rounded-2xl p-4 border border-slate-200 text-xs max-w-md mx-auto text-left space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-slate-500">Username:</span>
                  <span className="font-mono font-bold text-slate-900">@{createdSummary.username}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Work Category:</span>
                  <span className="font-bold text-slate-800">{createdSummary.category}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Job Role:</span>
                  <span className="font-bold text-slate-800">{createdSummary.designation}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Department:</span>
                  <span className="font-bold text-slate-800">{createdSummary.department}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Compensation:</span>
                  <span className="font-bold text-emerald-800">{createdSummary.salaryText}</span>
                </div>
              </div>

              <div className="flex justify-center gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setCurrentStep(1);
                    setFullName('');
                    setUsername('');
                    setMobile('');
                    setCreatedSummary(null);
                  }}
                  className="px-4 py-2.5 rounded-xl border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs transition-colors cursor-pointer"
                >
                  Register Another Staff
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="px-5 py-2.5 rounded-xl bg-emerald-800 hover:bg-emerald-700 text-white font-bold text-xs shadow-xs transition-colors cursor-pointer"
                >
                  Done / Close
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Wizard Footer Controls (Steps 1 to 6) */}
        {currentStep <= 6 && (
          <div className="px-6 py-3.5 border-t border-slate-200 bg-slate-50/80 flex items-center justify-between shrink-0">
            {currentStep > 1 ? (
              <button
                type="button"
                onClick={handleBack}
                className="px-4 py-2 rounded-xl border border-slate-200 hover:bg-slate-100 text-slate-700 font-bold text-xs transition-colors flex items-center gap-1.5 cursor-pointer"
              >
                <ChevronLeft size={15} />
                <span>Back</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-xl text-slate-500 hover:text-slate-800 text-xs font-semibold"
              >
                Cancel
              </button>
            )}

            {currentStep < 6 ? (
              <button
                type="button"
                onClick={handleNext}
                className="px-5 py-2.5 rounded-xl bg-emerald-800 hover:bg-emerald-700 text-white font-bold text-xs shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer"
              >
                <span>Continue</span>
                <ChevronRight size={15} />
              </button>
            ) : (
              <button
                type="button"
                disabled={isSubmitting}
                onClick={handleFinalSubmit}
                className="px-6 py-2.5 rounded-xl bg-emerald-800 hover:bg-emerald-700 text-white font-bold text-xs shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
              >
                {isSubmitting ? (
                  <span>Registering Staff…</span>
                ) : (
                  <>
                    <CheckCircle2 size={16} />
                    <span>Confirm & Register</span>
                  </>
                )}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
