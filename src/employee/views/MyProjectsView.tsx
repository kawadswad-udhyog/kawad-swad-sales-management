import React, { useState, useEffect } from 'react';
import { useStore } from '../../context/StoreContext';
import { apiFetch } from '../../services/api';
import { ProjectItem, ProjectMilestoneItem } from '../types';
import {
  Briefcase,
  CheckCircle2,
  Calendar,
  AlertCircle,
  Send,
  ExternalLink,
  X,
  FileCheck,
  Clock,
} from 'lucide-react';

export const MyProjectsView: React.FC = () => {
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [activeMilestone, setActiveMilestone] = useState<ProjectMilestoneItem | null>(null);
  const [notes, setNotes] = useState('');
  const [link, setLink] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  const fetchProjects = async () => {
    setIsLoading(true);
    try {
      const res = await apiFetch('/api/workforce/my-projects');
      if (res.ok) {
        const data = await res.json();
        setProjects(data);
      }
    } catch (err) {
      console.error('Failed to load projects:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  const handleSubmitMilestone = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeMilestone) return;
    if (!notes.trim()) {
      setErrorMessage('Please describe the deliverable details.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage('');
    setStatusMessage('');

    try {
      const res = await apiFetch(`/api/workforce/my-projects/milestones/${activeMilestone.milestone_id}/submit`, {
        method: 'POST',
        body: JSON.stringify({
          submission_notes: notes.trim(),
          submission_link: link.trim(),
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setStatusMessage('Milestone submitted successfully for Owner review!');
        await fetchProjects();
        setTimeout(() => {
          setActiveMilestone(null);
          setStatusMessage('');
        }, 1500);
      } else {
        setErrorMessage(data.detail || 'Failed to submit milestone.');
      }
    } catch (err) {
      setErrorMessage('Network error while submitting deliverable.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-black text-slate-900 m-0">
          Freelance Projects & Milestones
        </h1>
        <p className="text-xs sm:text-sm text-slate-500 mt-1">
          Contracts, deliverables, and payment milestones agreed with Kawad Swad Udhyog.
        </p>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-xs text-slate-400">Loading projects…</div>
      ) : projects.length === 0 ? (
        <div className="bg-white rounded-2xl border border-slate-200 p-8 text-center">
          <Briefcase size={32} className="mx-auto text-slate-300 mb-2" />
          <h3 className="text-sm font-bold text-slate-800 m-0">No Active Projects</h3>
          <p className="text-xs text-slate-500 mt-1">
            Projects assigned to you by the Business Owner will appear here.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {projects.map((proj) => (
            <div key={proj.project_id} className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
              <div className="p-5 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-50/50">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-bold text-slate-900 m-0">{proj.title}</h2>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-800">
                      {proj.status}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">{proj.description}</p>
                </div>
                <div className="text-right shrink-0">
                  <span className="text-xs text-slate-400 block">Total Budget</span>
                  <span className="text-lg font-black text-slate-900">
                    ₹{Number(proj.total_budget || 0).toLocaleString('en-IN')}
                  </span>
                </div>
              </div>

              {/* Milestones */}
              <div className="p-5">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">
                  Project Milestones
                </h3>

                {proj.milestones && proj.milestones.length > 0 ? (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {proj.milestones.map((ms) => (
                      <div
                        key={ms.milestone_id}
                        className="p-4 rounded-xl border border-slate-200 bg-white shadow-2xs flex flex-col justify-between"
                      >
                        <div>
                          <div className="flex items-center justify-between gap-2 mb-1.5">
                            <span className="text-xs font-bold text-slate-900">{ms.title}</span>
                            <span
                              className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                                ms.status === 'PAID'
                                  ? 'bg-emerald-100 text-emerald-800'
                                  : ms.status === 'APPROVED'
                                  ? 'bg-blue-100 text-blue-800'
                                  : ms.status === 'SUBMITTED'
                                  ? 'bg-amber-100 text-amber-800'
                                  : 'bg-slate-100 text-slate-700'
                              }`}
                            >
                              {ms.status}
                            </span>
                          </div>
                          <p className="text-xs text-slate-600 line-clamp-2">{ms.description}</p>
                          <div className="mt-2 text-xs font-bold text-emerald-700">
                            Payout: ₹{Number(ms.amount || 0).toLocaleString('en-IN')}
                          </div>

                          {ms.submission_notes && (
                            <div className="mt-2 p-2 rounded-lg bg-slate-50 border border-slate-100 text-[11px] text-slate-700">
                              <strong>Submission:</strong> {ms.submission_notes}
                              {ms.submission_link && (
                                <a
                                  href={ms.submission_link}
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

                          {ms.review_notes && (
                            <div className="mt-2 p-2 rounded-lg bg-emerald-50 text-[11px] text-emerald-900 border border-emerald-200">
                              <strong>Review:</strong> {ms.review_notes}
                            </div>
                          )}
                        </div>

                        <div className="mt-4 pt-3 border-t border-slate-100">
                          {ms.status !== 'APPROVED' && ms.status !== 'PAID' ? (
                            <button
                              onClick={() => {
                                setActiveMilestone(ms);
                                setNotes(ms.submission_notes || '');
                                setLink(ms.submission_link || '');
                                setErrorMessage('');
                                setStatusMessage('');
                              }}
                              className="w-full py-2 px-3 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white font-semibold text-xs shadow-2xs transition-colors flex items-center justify-center gap-1.5 cursor-pointer"
                            >
                              <Send size={13} />
                              <span>{ms.status === 'SUBMITTED' ? 'Update Submission' : 'Submit Deliverable'}</span>
                            </button>
                          ) : (
                            <div className="text-center text-xs font-semibold text-emerald-700 flex items-center justify-center gap-1 py-1">
                              <CheckCircle2 size={14} />
                              <span>{ms.status === 'PAID' ? 'Disbursed & Paid' : 'Approved by Owner'}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-slate-400 py-3">No milestones defined for this project.</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Milestone Deliverable Modal */}
      {activeMilestone && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-lg w-full border border-slate-200 shadow-xl overflow-hidden animate-in fade-in zoom-in-95">
            <div className="p-4 sm:p-5 bg-slate-900 text-white flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold text-white m-0">Submit Milestone Deliverable</h3>
                <p className="text-xs text-slate-300 mt-0.5">{activeMilestone.title}</p>
              </div>
              <button
                onClick={() => setActiveMilestone(null)}
                className="text-slate-400 hover:text-white p-1 rounded-md"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSubmitMilestone} className="p-5 space-y-4">
              {errorMessage && (
                <div className="p-3 rounded-xl bg-red-50 text-red-700 text-xs border border-red-200 flex items-center gap-2">
                  <AlertCircle size={16} />
                  <span>{errorMessage}</span>
                </div>
              )}

              {statusMessage && (
                <div className="p-3 rounded-xl bg-emerald-50 text-emerald-800 text-xs border border-emerald-200 flex items-center gap-2">
                  <CheckCircle2 size={16} />
                  <span>{statusMessage}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Deliverable Summary & Notes <span className="text-red-500">*</span>
                </label>
                <textarea
                  rows={4}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Explain completed work, changes made, and files delivered…"
                  className="w-full text-xs p-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-600"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Deliverable / Asset Link
                </label>
                <input
                  type="url"
                  value={link}
                  onChange={(e) => setLink(e.target.value)}
                  placeholder="https://drive.google.com/… or Figma / repository link"
                  className="w-full text-xs p-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-600"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setActiveMilestone(null)}
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
