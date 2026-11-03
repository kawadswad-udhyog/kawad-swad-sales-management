import React, { useState, useEffect } from 'react';
import { useStore } from '../../context/StoreContext';
import { apiFetch } from '../../services/api';
import {
  User,
  Phone,
  Mail,
  MapPin,
  HeartPulse,
  CreditCard,
  Building,
  CheckCircle2,
  AlertCircle,
  Save,
  ShieldCheck,
} from 'lucide-react';

export const MyProfileView: React.FC = () => {
  const { currentUser } = useStore();
  const [profile, setProfile] = useState<any>(null);
  const [mobile, setMobile] = useState('');
  const [email, setEmail] = useState('');
  const [address, setAddress] = useState('');
  const [emergencyContact, setEmergencyContact] = useState('');
  const [bankDetails, setBankDetails] = useState('');

  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  const fetchProfile = async () => {
    setIsLoading(true);
    try {
      const res = await apiFetch('/api/workforce/my-profile');
      if (res.ok) {
        const data = await res.json();
        setProfile(data);
        setMobile(data.mobile || '');
        setEmail(data.email || '');
        setAddress(data.address || '');
        setEmergencyContact(data.emergency_contact || '');
        setBankDetails(data.bank_details || '');
      }
    } catch (err) {
      console.error('Failed to load profile:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchProfile();
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setStatusMessage('');
    setErrorMessage('');

    try {
      const res = await apiFetch('/api/workforce/my-profile', {
        method: 'PUT',
        body: JSON.stringify({
          mobile: mobile.trim(),
          email: email.trim(),
          address: address.trim(),
          emergency_contact: emergencyContact.trim(),
          bank_details: bankDetails.trim(),
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setStatusMessage('Personal contact and banking details updated successfully!');
        await fetchProfile();
      } else {
        setErrorMessage(data.detail || 'Failed to update profile.');
      }
    } catch (err) {
      setErrorMessage('Network error while saving profile.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-black text-slate-900 m-0">
          My Staff Profile & Banking
        </h1>
        <p className="text-xs sm:text-sm text-slate-500 mt-1">
          Review your official employee profile and keep emergency contact & payout accounts updated.
        </p>
      </div>

      {statusMessage && (
        <div className="p-3.5 rounded-xl bg-emerald-50 text-emerald-800 text-xs border border-emerald-200 flex items-center gap-2">
          <CheckCircle2 size={16} />
          <span>{statusMessage}</span>
        </div>
      )}

      {errorMessage && (
        <div className="p-3.5 rounded-xl bg-red-50 text-red-700 text-xs border border-red-200 flex items-center gap-2">
          <AlertCircle size={16} />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Official Identity (Read-only) */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-xs p-6 space-y-4">
        <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
          <ShieldCheck size={18} className="text-emerald-700" />
          <h2 className="text-sm font-bold text-slate-900 m-0">Official Designation & Master Record</h2>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-xs">
          <div>
            <span className="text-slate-400 font-medium block">Employee ID</span>
            <span className="font-bold text-slate-900 mt-0.5 block">{profile?.user_id || currentUser?.user_id}</span>
          </div>

          <div>
            <span className="text-slate-400 font-medium block">Full Legal Name</span>
            <span className="font-bold text-slate-900 mt-0.5 block">{profile?.full_name || currentUser?.full_name}</span>
          </div>

          <div>
            <span className="text-slate-400 font-medium block">Username / Account</span>
            <span className="font-bold text-slate-900 mt-0.5 block">@{profile?.username || currentUser?.username}</span>
          </div>

          <div>
            <span className="text-slate-400 font-medium block">Assigned Role</span>
            <span className="font-bold text-emerald-700 mt-0.5 block">{profile?.role || currentUser?.role}</span>
          </div>

          <div>
            <span className="text-slate-400 font-medium block">Department</span>
            <span className="font-bold text-slate-900 mt-0.5 block">{profile?.department || 'Operations'}</span>
          </div>

          <div>
            <span className="text-slate-400 font-medium block">Joining Date</span>
            <span className="font-bold text-slate-900 mt-0.5 block">{profile?.joining_date || 'Active Member'}</span>
          </div>
        </div>
      </div>

      {/* Self-Service Contact & Banking Form */}
      <form onSubmit={handleSave} className="bg-white rounded-2xl border border-slate-200 shadow-xs p-6 space-y-4">
        <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
          <CreditCard size={18} className="text-emerald-700" />
          <h2 className="text-sm font-bold text-slate-900 m-0">Contact & Salary Payout Details</h2>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">
              Mobile Number
            </label>
            <div className="relative">
              <Phone size={14} className="absolute left-3 top-3 text-slate-400" />
              <input
                type="tel"
                value={mobile}
                onChange={(e) => setMobile(e.target.value)}
                placeholder="+91 98765 43210"
                className="w-full text-xs pl-8 pr-3 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-600"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">
              Email Address
            </label>
            <div className="relative">
              <Mail size={14} className="absolute left-3 top-3 text-slate-400" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="w-full text-xs pl-8 pr-3 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-600"
              />
            </div>
          </div>
        </div>

        <div>
          <label className="block text-xs font-bold text-slate-700 mb-1">
            Residential Address
          </label>
          <div className="relative">
            <MapPin size={14} className="absolute left-3 top-3 text-slate-400" />
            <input
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="City, District, Rajasthan"
              className="w-full text-xs pl-8 pr-3 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-600"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-bold text-slate-700 mb-1">
            Emergency Contact Name & Phone
          </label>
          <div className="relative">
            <HeartPulse size={14} className="absolute left-3 top-3 text-slate-400" />
            <input
              type="text"
              value={emergencyContact}
              onChange={(e) => setEmergencyContact(e.target.value)}
              placeholder="e.g. Ramesh Kumar (Brother) - 98290 12345"
              className="w-full text-xs pl-8 pr-3 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-600"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-bold text-slate-700 mb-1">
            Bank Account / UPI Details for Salary Direct Credit
          </label>
          <textarea
            rows={2}
            value={bankDetails}
            onChange={(e) => setBankDetails(e.target.value)}
            placeholder="Account No: 1234567890 | Bank: SBI Bikaner | IFSC: SBIN0001234 | UPI: name@okhdfcbank"
            className="w-full text-xs p-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-600"
          />
        </div>

        <div className="pt-3 border-t border-slate-100 flex justify-end">
          <button
            type="submit"
            disabled={isSaving}
            className="px-6 py-2.5 rounded-xl text-xs font-bold bg-emerald-700 hover:bg-emerald-800 text-white shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
          >
            <Save size={14} />
            <span>{isSaving ? 'Saving Changes…' : 'Save Details'}</span>
          </button>
        </div>
      </form>
    </div>
  );
};
