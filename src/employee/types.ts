export type EmployeeViewType =
  | 'overview'
  | 'tasks'
  | 'attendance'
  | 'salary'
  | 'projects'
  | 'profile';

export interface TaskItem {
  task_id: string;
  title: string;
  description: string;
  assigned_to_user_id: string;
  assigned_to_name: string;
  role: string;
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'URGENT';
  status: 'PENDING' | 'IN_PROGRESS' | 'SUBMITTED' | 'APPROVED' | 'REJECTED' | 'COMPLETED';
  due_date: string;
  created_by: string;
  submission_notes: string;
  proof_url: string;
  review_notes: string;
  created_at: string;
  completed_at: string;
}

export interface AttendanceItem {
  attendance_id: string;
  employee_id: string;
  employee_name: string;
  attendance_date: string;
  check_in_time: string;
  check_out_time: string;
  total_hours: number;
  status: 'PRESENT' | 'ABSENT' | 'HALF_DAY' | 'LEAVE';
  notes: string;
}

export interface SalaryStructureData {
  structure_id: string;
  user_id: string;
  basic_salary: number;
  hra: number;
  transport_allowance: number;
  special_allowance: number;
  sales_commission_rate: number;
  pf_deduction: number;
  tds_deduction: number;
  other_deductions: number;
  payment_mode: string;
  effective_from: string;
}

export interface PayrollItemData {
  item_id: string;
  payroll_run_id: string;
  user_id: string;
  employee_name: string;
  role: string;
  base_salary: number;
  working_days: number;
  present_days: number;
  earned_basic: number;
  allowances: number;
  incentive_amount: number;
  bonus_amount: number;
  deductions: number;
  adjustment_amount: number;
  gross_amount: number;
  net_amount: number;
  payment_status: 'UNPAID' | 'PAID';
  notes: string;
}

export interface ProjectMilestoneItem {
  milestone_id: string;
  project_id: string;
  title: string;
  description: string;
  amount: number;
  due_date: string;
  status: 'PENDING' | 'IN_PROGRESS' | 'SUBMITTED' | 'APPROVED' | 'PAID';
  submission_notes: string;
  submission_link: string;
  review_notes: string;
}

export interface ProjectItem {
  project_id: string;
  title: string;
  description: string;
  freelancer_user_id: string;
  total_budget: number;
  currency: string;
  start_date: string;
  target_completion_date: string;
  status: 'IN_PROGRESS' | 'REVIEW' | 'COMPLETED' | 'ON_HOLD';
  deliverables_summary: string;
  milestones?: ProjectMilestoneItem[];
}
