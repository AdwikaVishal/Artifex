import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useSubmitReferral } from '@/hooks/use-foster'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { Input, Select, TextArea } from '@/components/ui/input'
import { ToggleGroup } from '@/components/ui/toggle-group'
import { toast } from '@/components/ui/toast'
import { motion } from 'framer-motion'
import { ArrowLeft, Send, Sparkles } from 'lucide-react'
import type { ReferralSubmission } from '@/types'

const emergencyLevels = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
]

const genderOptions = [
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'non-binary', label: 'Non-binary' },
]

const homeTypeOptions = [
  { value: 'traditional', label: 'Traditional' },
  { value: 'therapeutic', label: 'Therapeutic' },
  { value: 'specialized', label: 'Specialized' },
  { value: 'emergency', label: 'Emergency Shelter' },
  { value: 'kinship', label: 'Kinship Care' },
]

const medicalOptions = [
  { value: 'none', label: 'None' },
  { value: 'physical_disability', label: 'Physical Disability' },
  { value: 'chronic_condition', label: 'Chronic Condition' },
  { value: 'developmental_delay', label: 'Developmental Delay' },
  { value: 'medication_management', label: 'Medication Management' },
]

const behavioralOptions = [
  { value: 'none', label: 'None' },
  { value: 'trauma_counseling', label: 'Trauma Counseling' },
  { value: 'behavioral_therapy', label: 'Behavioral Therapy' },
  { value: 'anger_management', label: 'Anger Management' },
  { value: 'social_skills', label: 'Social Skills Training' },
  { value: 'substance_support', label: 'Substance Support' },
]

const accessibilityOptions = [
  { value: 'wheelchair', label: 'Wheelchair Access' },
  { value: 'medical_equipment', label: 'Medical Equipment Storage' },
  { value: 'sensory_room', label: 'Sensory Room' },
  { value: 'elevator', label: 'Elevator Access' },
]

const riskFlagOptions = [
  { value: 'history_of_trauma', label: 'History of Trauma' },
  { value: 'medical_complexity', label: 'Medical Complexity' },
  { value: 'behavioral_concerns', label: 'Behavioral Concerns' },
  { value: 'sibling_separation', label: 'Sibling Separation Risk' },
  { value: 'placement_instability', label: 'Placement Instability' },
  { value: 'legal_issues', label: 'Legal Issues' },
]

const locationOptions = [
  { value: 'urban', label: 'Urban' },
  { value: 'suburban', label: 'Suburban' },
  { value: 'rural', label: 'Rural' },
]

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.05 },
  },
}

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0 },
}

export default function ReferralPage() {
  const navigate = useNavigate()
  const submitReferral = useSubmitReferral()

  const [form, setForm] = useState<ReferralSubmission>({
    child_id: '',
    age: 0,
    gender: '',
    special_needs: false,
    languages: '',
    medical_needs: '',
    behavioral_support: '',
    sibling_group: false,
    emergency_level: 'medium',
    preferred_location: '',
    foster_home_type: '',
    capacity_needed: 1,
    accessibility_needs: false,
    school_continuity: false,
    risk_flags: [],
    notes: '',
  })

  const [errors, setErrors] = useState<Partial<Record<keyof ReferralSubmission, string>>>({})

  const updateField = <K extends keyof ReferralSubmission>(key: K, value: ReferralSubmission[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    if (errors[key]) {
      setErrors((prev) => ({ ...prev, [key]: undefined }))
    }
  }

  const validate = (): boolean => {
    const newErrors: Partial<Record<keyof ReferralSubmission, string>> = {}
    if (!form.child_id.trim()) newErrors.child_id = 'Child ID is required'
    if (!form.age || form.age < 0 || form.age > 18) newErrors.age = 'Age must be between 0 and 18'
    if (!form.gender) newErrors.gender = 'Gender is required'
    if (!form.preferred_location) newErrors.preferred_location = 'Location is required'
    if (!form.foster_home_type) newErrors.foster_home_type = 'Home type is required'
    if (form.capacity_needed < 1) newErrors.capacity_needed = 'Capacity must be at least 1'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) {
      toast({ title: 'Validation Error', description: 'Please fix the form errors', variant: 'error' })
      return
    }

    try {
      const result = await submitReferral.mutateAsync(form)
      toast({
        title: 'Referral Submitted',
        description: `Workflow ID: ${result.workflow_id}`,
        variant: 'success',
      })
      navigate(`/workflow/${result.workflow_id}`)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to submit referral'
      console.error('[referral] submission error:', err)
      toast({
        title: 'Submission Failed',
        description: message,
        variant: 'error',
      })
    }
  }

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="space-y-6">
      <motion.div variants={item}>
        <div className="flex items-center gap-4 mb-1">
          <Link to="/" className="text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft size={20} />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-foreground">New Referral</h1>
            <p className="text-sm text-muted-foreground mt-1">Submit a new foster care referral to the orchestration engine</p>
          </div>
        </div>
      </motion.div>

      <motion.div variants={item}>
        <form onSubmit={handleSubmit}>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-6">
              <GlassCard>
                <GlassCardHeader>
                  <GlassCardTitle>Child Information</GlassCardTitle>
                </GlassCardHeader>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <Input
                    id="child_id"
                    label="Child ID"
                    placeholder="e.g. CH-2024-001"
                    value={form.child_id}
                    onChange={(e) => updateField('child_id', e.target.value)}
                    error={errors.child_id}
                  />
                  <Input
                    id="age"
                    label="Age"
                    type="number"
                    min={0}
                    max={18}
                    placeholder="0-18"
                    value={form.age || ''}
                    onChange={(e) => updateField('age', parseInt(e.target.value) || 0)}
                    error={errors.age}
                  />
                  <Select
                    id="gender"
                    label="Gender"
                    placeholder="Select gender"
                    options={genderOptions}
                    value={form.gender}
                    onChange={(e) => updateField('gender', e.target.value)}
                    error={errors.gender}
                  />
                  <Select
                    id="emergency_level"
                    label="Emergency Level"
                    options={emergencyLevels}
                    value={form.emergency_level}
                    onChange={(e) => updateField('emergency_level', e.target.value as ReferralSubmission['emergency_level'])}
                  />
                  <Input
                    id="languages"
                    label="Languages"
                    placeholder="e.g. English, Spanish, ASL"
                    value={form.languages}
                    onChange={(e) => updateField('languages', e.target.value)}
                  />
                  <div className="flex items-center gap-6 pt-6">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={form.special_needs}
                        onChange={(e) => updateField('special_needs', e.target.checked)}
                        className="w-4 h-4 rounded border-border-light bg-surface-alt accent-primary"
                      />
                      <span className="text-sm text-foreground">Special Needs</span>
                    </label>
                  </div>
                </div>
              </GlassCard>

              <GlassCard>
                <GlassCardHeader>
                  <GlassCardTitle>Placement Requirements</GlassCardTitle>
                </GlassCardHeader>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <Select
                    id="preferred_location"
                    label="Preferred Location"
                    placeholder="Select location"
                    options={locationOptions}
                    value={form.preferred_location}
                    onChange={(e) => updateField('preferred_location', e.target.value)}
                    error={errors.preferred_location}
                  />
                  <Select
                    id="foster_home_type"
                    label="Foster Home Type"
                    placeholder="Select type"
                    options={homeTypeOptions}
                    value={form.foster_home_type}
                    onChange={(e) => updateField('foster_home_type', e.target.value)}
                    error={errors.foster_home_type}
                  />
                  <Input
                    id="capacity_needed"
                    label="Capacity Needed"
                    type="number"
                    min={1}
                    placeholder="Number of placements needed"
                    value={form.capacity_needed || ''}
                    onChange={(e) => updateField('capacity_needed', parseInt(e.target.value) || 1)}
                    error={errors.capacity_needed}
                  />
                  <div className="flex items-center gap-6 pt-6">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={form.sibling_group}
                        onChange={(e) => updateField('sibling_group', e.target.checked)}
                        className="w-4 h-4 rounded border-border-light bg-surface-alt accent-primary"
                      />
                      <span className="text-sm text-foreground">Sibling Group</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={form.school_continuity}
                        onChange={(e) => updateField('school_continuity', e.target.checked)}
                        className="w-4 h-4 rounded border-border-light bg-surface-alt accent-primary"
                      />
                      <span className="text-sm text-foreground">School Continuity</span>
                    </label>
                  </div>
                </div>
              </GlassCard>

              <GlassCard>
                <GlassCardHeader>
                  <GlassCardTitle>Medical & Behavioral Needs</GlassCardTitle>
                </GlassCardHeader>
                <div className="space-y-4">
                  <ToggleGroup
                    label="Medical Needs"
                    options={medicalOptions}
                    value={form.medical_needs}
                    onChange={(v) => updateField('medical_needs', v as string)}
                  />
                  <ToggleGroup
                    label="Behavioral Support"
                    options={behavioralOptions}
                    value={form.behavioral_support}
                    onChange={(v) => updateField('behavioral_support', v as string)}
                  />
                </div>
              </GlassCard>
            </div>

            <div className="space-y-6">
              <GlassCard>
                <GlassCardHeader>
                  <GlassCardTitle>Accessibility & Risk</GlassCardTitle>
                </GlassCardHeader>
                <div className="space-y-4">
                  <div className="space-y-4">
                    <div>
                      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Accessibility Needs</p>
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={form.accessibility_needs}
                          onChange={(e) => updateField('accessibility_needs', e.target.checked)}
                          className="w-4 h-4 rounded border-border-light bg-surface-alt accent-primary"
                        />
                        <span className="text-sm text-foreground">Requires accessibility accommodations</span>
                      </label>
                    </div>
                    <ToggleGroup
                      label="Risk Flags"
                      options={riskFlagOptions}
                      value={form.risk_flags}
                      onChange={(v) => updateField('risk_flags', v as string[])}
                      multiple
                    />
                  </div>
                </div>
              </GlassCard>

              <GlassCard>
                <GlassCardHeader>
                  <GlassCardTitle>Additional Notes</GlassCardTitle>
                </GlassCardHeader>
                <TextArea
                  id="notes"
                  placeholder="Any additional information or special requirements..."
                  value={form.notes || ''}
                  onChange={(e) => updateField('notes', e.target.value)}
                  className="min-h-[120px]"
                />
              </GlassCard>

              <Button
                type="submit"
                size="lg"
                loading={submitReferral.isPending}
                className="w-full"
              >
                <Send size={16} />
                Submit Referral
              </Button>

              <div className="glass-card p-4 space-y-2">
                <div className="flex items-center gap-2 text-primary">
                  <Sparkles size={14} />
                  <span className="text-xs font-semibold uppercase tracking-wider">Automated</span>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  The orchestration engine will automatically match, analyze risk, and route this referral through the approval workflow.
                </p>
              </div>
            </div>
          </div>
        </form>
      </motion.div>
    </motion.div>
  )
}
