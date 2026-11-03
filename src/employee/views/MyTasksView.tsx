import React, { useState, useEffect } from 'react';
import { useStore } from '../../context/StoreContext';
import { apiFetch } from '../../services/api';
import { TaskItem } from '../types';
import {
  CheckSquare,
  Clock,
  Calendar,
  AlertCircle,
  Send,
  ExternalLink,
  MessageSquare,
  CheckCircle2,
  X,
  Filter,
} from 'lucide-react';

export const MyTasksView: React.FC = () => {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [filter, setFilter] = useState<string>('ALL');
  const [isLoading, setIsLoading] = useState(true);
  const [activeTask, setActiveTask] = useState<TaskItem | null>(null);
  const [submissionNotes, setSubmissionNotes] = useState('');
  const [proofUrl, setProofUrl] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [submitSuccess, setSubmitSuccess] = useState('');

  const fetchTasks = async () => {
    setIsLoading(true);
    try {
      const res = await apiFetch('/api/workforce/my-tasks');
      if (res.ok) {
        const data = await res.json();
        setTasks(data);
      }
    } catch (err) {
      console.error('Failed to load tasks:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTasks();
  }, []);

  const handleSubmitTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeTask) return;
    if (!submissionNotes.trim()) {
      setSubmitError('Please provide submission notes detailing the work done.');
      return;
    }

    setIsSubmitting(true);
    setSubmitError('');
    setSubmitSuccess('');

    try {
      const res = await apiFetch(`/api/workforce/my-tasks/${activeTask.task_id}/submit`, {
        method: 'POST',
        body: JSON.stringify({
          submission_notes: submissionNotes.trim(),
          proof_url: proofUrl.trim(),
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setSubmitSuccess('Task deliverable submitted successfully for Owner review!');
        setSubmissionNotes('');
        setProofUrl('');
        await fetchTasks();
        setTimeout(() => {
          setActiveTask(null);
          setSubmitSuccess('');
        }, 1500);
      } else {
        setSubmitError(data.detail || 'Failed to submit task.');
      }
    } catch (err) {
      setSubmitError('Network error while submitting task.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const filteredTasks = tasks.filter((t) => {
    if (filter === 'ALL') return true;
    if (filter === 'PENDING') return t.status === 'PENDING' || t.status === 'IN_PROGRESS';
    return t.status === filter;
  });

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-black text-slate-900 m-0">
            My Work Assignments
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Deliverables and task instructions assigned by the Owner & PA.
          </p>
        </div>

        {/* Status Filters */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
          {['ALL', 'PENDING', 'SUBMITTED', 'APPROVED', 'COMPLETED'].map((st) => (
            <button
              key={st}
              onClick={() => setFilter(st)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors cursor-pointer ${
                filter === st
                  ? 'bg-emerald-700 text-white shadow-xs'
                  : 'bg-white text-slate-600 hover:bg-slate-100 border border-slate-200'
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Tasks List */}
      {isLoading ? (
        <div className="text-center py-12 text-xs text-slate-400">Loading assignments…</div>
      ) : filteredTasks.length === 0 ? (
        <div className="bg-white rounded-2xl border border-slate-200 p-8 text-center">
          <CheckSquare size={32} className="mx-auto text-slate-300 mb-2" />
          <h3 className="text-sm font-bold text-slate-800 m-0">No tasks in this category</h3>
          <p className="text-xs text-slate-500 mt-1">You are all caught up on your assignments.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredTasks.map((task) => (
            <div
              key={task.task_id}
              className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 flex flex-col justify-between hover:border-slate-300 transition-colors"
            >
              <div>
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                      task.priority === 'URGENT'
                        ? 'bg-red-100 text-red-800'
                        : task.priority === 'HIGH'
                        ? 'bg-amber-100 text-amber-800'
                        : 'bg-slate-100 text-slate-700'
                    }`}
                  >
                    {task.priority} PRIORITY
                  </span>
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                      task.status === 'COMPLETED' || task.status === 'APPROVED'
                        ? 'bg-emerald-100 text-emerald-800'
                        : task.status === 'SUBMITTED'
                        ? 'bg-blue-100 text-blue-800'
                        : 'bg-amber-100 text-amber-800'
                    }`}
                  >
                    {task.status}
                  </span>
                </div>

                <h3 className="text-sm font-bold text-slate-900 m-0">{task.title}</h3>
                <p className="text-xs text-slate-600 mt-2 line-clamp-3">
                  {task.description || 'No detailed instructions provided.'}
                </p>

                {task.due_date && (
                  <div className="text-[11px] text-slate-500 mt-3 flex items-center gap-1.5">
                    <Calendar size={13} className="text-slate-400" />
                    <span>Due Date: <strong>{task.due_date}</strong></span>
                  </div>
                )}

                {task.submission_notes && (
                  <div className="mt-3 p-2.5 rounded-lg bg-blue-50/60 border border-blue-100 text-[11px] text-blue-900">
                    <strong>My Submission:</strong> {task.submission_notes}
                    {task.proof_url && (
                      <a
                        href={task.proof_url}
                        target="_blank"
                        rel="noreferrer"
                        className="block mt-1 text-emerald-700 font-semibold underline flex items-center gap-1"
                      >
                        <span>View Deliverable Link</span>
                        <ExternalLink size={11} />
                      </a>
                    )}
                  </div>
                )}

                {task.review_notes && (
                  <div className="mt-2.5 p-2.5 rounded-lg bg-emerald-50/80 border border-emerald-200 text-[11px] text-emerald-900">
                    <strong>Review Feedback:</strong> {task.review_notes}
                  </div>
                )}
              </div>

              {/* Action Button */}
              <div className="mt-4 pt-3 border-t border-slate-100">
                {task.status !== 'APPROVED' && task.status !== 'COMPLETED' ? (
                  <button
                    onClick={() => {
                      setActiveTask(task);
                      setSubmissionNotes(task.submission_notes || '');
                      setProofUrl(task.proof_url || '');
                      setSubmitError('');
                      setSubmitSuccess('');
                    }}
                    className="w-full py-2 px-3 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-semibold text-xs shadow-xs transition-colors flex items-center justify-center gap-1.5 cursor-pointer"
                  >
                    <Send size={13} />
                    <span>{task.status === 'SUBMITTED' ? 'Edit Submission' : 'Submit Deliverable'}</span>
                  </button>
                ) : (
                  <div className="text-center text-xs font-semibold text-emerald-700 flex items-center justify-center gap-1 py-1">
                    <CheckCircle2 size={14} />
                    <span>Completed & Verified</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Submission Modal */}
      {activeTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-lg w-full border border-slate-200 shadow-xl overflow-hidden animate-in fade-in zoom-in-95">
            <div className="p-4 sm:p-5 bg-slate-900 text-white flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold text-white m-0">Submit Deliverable</h3>
                <p className="text-xs text-slate-300 mt-0.5 line-clamp-1">{activeTask.title}</p>
              </div>
              <button
                onClick={() => setActiveTask(null)}
                className="text-slate-400 hover:text-white p-1 rounded-md"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSubmitTask} className="p-5 space-y-4">
              {submitError && (
                <div className="p-3 rounded-xl bg-red-50 text-red-700 text-xs border border-red-200 flex items-center gap-2">
                  <AlertCircle size={16} />
                  <span>{submitError}</span>
                </div>
              )}

              {submitSuccess && (
                <div className="p-3 rounded-xl bg-emerald-50 text-emerald-800 text-xs border border-emerald-200 flex items-center gap-2">
                  <CheckCircle2 size={16} />
                  <span>{submitSuccess}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Work Completion Details / Notes <span className="text-red-500">*</span>
                </label>
                <textarea
                  rows={4}
                  value={submissionNotes}
                  onChange={(e) => setSubmissionNotes(e.target.value)}
                  placeholder="Describe the completed work, outcomes, customer visits made, or design created…"
                  className="w-full text-xs p-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-600 focus:border-transparent"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Proof / Deliverable URL (Optional)
                </label>
                <input
                  type="url"
                  value={proofUrl}
                  onChange={(e) => setProofUrl(e.target.value)}
                  placeholder="https://drive.google.com/… or Figma / image link"
                  className="w-full text-xs p-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-600 focus:border-transparent"
                />
                <p className="text-[10px] text-slate-400 mt-1">
                  Provide a link to Google Drive, design file, photo upload, or invoice copy.
                </p>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setActiveTask(null)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-5 py-2 rounded-xl text-xs font-semibold bg-emerald-700 hover:bg-emerald-800 text-white shadow-xs disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
                >
                  <Send size={14} />
                  <span>{isSubmitting ? 'Submitting…' : 'Submit for Review'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
