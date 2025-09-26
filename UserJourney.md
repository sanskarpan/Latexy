# Latexy User Journey Map

## 🎯 User Personas & Journey Flows

### 1. Anonymous User (Trial Experience)

#### Journey: Discovery → Trial → Conversion
```
Landing Page → Try Editor → Usage Tracking → Registration Prompt → Sign Up
     ↓              ↓              ↓                ↓               ↓
  Marketing    Trial Editor   Device Tracking   Auth Modal    Full Access
   Content     (3 Free Uses)  (Anti-Abuse)     (Better-Auth)  (Dashboard)
```

**Detailed Flow:**
1. **Landing Page** (`/`)
   - Hero section with clear value proposition
   - "Try Now - No Sign Up Required" CTA
   - Feature highlights and testimonials
   - Pricing preview

2. **Trial Editor** (`/try`)
   - Simplified editor interface
   - LaTeX compilation (3 free uses)
   - PDF preview and download
   - Usage counter display
   - Registration prompt after 2nd use

3. **Registration Prompt**
   - Modal overlay after 3rd use
   - "Continue with unlimited access" message
   - Sign up form with social login options
   - Clear benefit explanation

### 2. Registered User (Free Plan)

#### Journey: Dashboard → Editor → History → Upgrade
```
Dashboard → Resume Editor → Compilation → History → Billing
    ↓           ↓              ↓           ↓         ↓
 Overview   Full Features   PDF Output   Version   Upgrade
 Analytics   (Limited)      Download     Control   Prompt
```

**Detailed Flow:**
1. **Dashboard** (`/dashboard`)
   - Welcome message and onboarding
   - Recent resumes and compilations
   - Usage statistics (monthly limits)
   - Quick actions (New Resume, Templates)

2. **Resume Editor** (`/editor`)
   - Full LaTeX editor with syntax highlighting
   - Job description input panel
   - Real-time PDF preview
   - Save and version control
   - Limited optimizations (upgrade prompt)

3. **Resume History** (`/history`)
   - List of all created resumes
   - Compilation history with timestamps
   - Download previous PDFs
   - Resume templates and favorites

4. **Settings** (`/settings`)
   - Profile management
   - Notification preferences
   - Account security
   - Data export/deletion (GDPR)

### 3. Premium User (Paid Subscription)

#### Journey: Full Feature Access → Advanced Tools → Analytics
```
Dashboard → Advanced Editor → AI Optimization → Analytics → API Keys
    ↓           ↓                  ↓              ↓           ↓
 Enhanced   Unlimited Features  LLM-Powered    Usage      BYOK
 Overview   (All Tools)         Enhancement    Insights   Management
```

**Detailed Flow:**
1. **Enhanced Dashboard** (`/dashboard`)
   - Advanced analytics and insights
   - Performance metrics
   - Optimization suggestions
   - Premium feature highlights

2. **Advanced Editor** (`/editor`)
   - Unlimited compilations and optimizations
   - Multiple LLM provider options
   - Advanced templates and themes
   - Collaboration features
   - Export to multiple formats

3. **AI Optimization** (`/optimize`)
   - Job-specific resume optimization
   - ATS scoring and recommendations
   - Keyword analysis and suggestions
   - A/B testing for different versions
   - Industry-specific templates

4. **Analytics Dashboard** (`/analytics`)
   - Resume performance metrics
   - Application success tracking
   - ATS compatibility scores
   - Optimization impact analysis

### 4. BYOK User (Bring Your Own Key)

#### Journey: API Key Setup → Custom Models → Advanced Features
```
Settings → API Keys → Provider Setup → Model Selection → Enhanced Editor
    ↓         ↓           ↓              ↓               ↓
 Account   Key Mgmt   Provider Config  Custom Models  Full Control
 Config    Interface   (OpenAI/etc)    Selection      Features
```

**Detailed Flow:**
1. **API Key Management** (`/api-keys`)
   - Add/remove API keys for different providers
   - Key validation and testing
   - Usage monitoring and quotas
   - Provider-specific settings

2. **Provider Configuration**
   - OpenAI: GPT-4, GPT-3.5-turbo
   - Anthropic: Claude-3 variants
   - Google: Gemini Pro models
   - Custom endpoints support

3. **Enhanced Editor Experience**
   - Access to latest models
   - Custom prompt engineering
   - Advanced optimization parameters
   - Cost tracking and optimization

## 🎨 Page-by-Page User Experience

### Landing Page (`/`)
```
┌─────────────────────────────────────────────────────────────┐
│                        HEADER                               │
│  Logo    Navigation    [Try Free] [Sign In] [Sign Up]      │
├─────────────────────────────────────────────────────────────┤
│                        HERO SECTION                        │
│  "AI-Powered ATS Resume Optimizer"                         │
│  "Create ATS-friendly resumes with LaTeX precision"        │
│  [Try Now - No Sign Up Required] [View Pricing]            │
├─────────────────────────────────────────────────────────────┤
│                      FEATURES GRID                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │
│  │LaTeX    │ │AI       │ │ATS      │ │Multi    │          │
│  │Editor   │ │Optimize │ │Scoring  │ │Format   │          │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘          │
├─────────────────────────────────────────────────────────────┤
│                      TESTIMONIALS                          │
│  User reviews and success stories                          │
├─────────────────────────────────────────────────────────────┤
│                      PRICING PREVIEW                       │
│  Free Trial → Basic → Pro → BYOK                          │
└─────────────────────────────────────────────────────────────┘
```

### Trial Editor (`/try`)
```
┌─────────────────────────────────────────────────────────────┐
│  TRIAL HEADER                                               │
│  "Free Trial: 2/3 uses remaining" [Sign Up for More]       │
├─────────────────────────────────────────────────────────────┤
│  EDITOR LAYOUT                                              │
│  ┌─────────────────┐ ┌─────────────────┐ ┌───────────────┐ │
│  │ LaTeX Editor    │ │ Job Description │ │ PDF Preview   │ │
│  │                 │ │                 │ │               │ │
│  │ [Sample Resume] │ │ [Paste Job]     │ │ [Loading...]  │ │
│  │                 │ │                 │ │               │ │
│  └─────────────────┘ └─────────────────┘ └───────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  ACTION BAR                                                 │
│  [Compile PDF] [Download] [Save (Sign Up Required)]        │
└─────────────────────────────────────────────────────────────┘
```

### User Dashboard (`/dashboard`)
```
┌─────────────────────────────────────────────────────────────┐
│  DASHBOARD HEADER                                           │
│  Welcome back, [Name]! [Profile] [Settings] [Sign Out]     │
├─────────────────────────────────────────────────────────────┤
│  STATS OVERVIEW                                             │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │
│  │Resumes  │ │This     │ │Success  │ │Plan     │          │
│  │Created  │ │Month    │ │Rate     │ │Usage    │          │
│  │   12    │ │  8/50   │ │  85%    │ │ 40/50   │          │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘          │
├─────────────────────────────────────────────────────────────┤
│  RECENT RESUMES                                             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Software Engineer Resume    [Edit] [Download] [Clone]   │ │
│  │ Data Scientist Resume       [Edit] [Download] [Clone]   │ │
│  │ Product Manager Resume      [Edit] [Download] [Clone]   │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  QUICK ACTIONS                                              │
│  [New Resume] [Browse Templates] [Upload .tex] [Upgrade]    │
└─────────────────────────────────────────────────────────────┘
```

### API Keys Management (`/api-keys`)
```
┌─────────────────────────────────────────────────────────────┐
│  API KEYS HEADER                                            │
│  "Bring Your Own Keys" [Add New Key]                       │
├─────────────────────────────────────────────────────────────┤
│  PROVIDER LIST                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ OpenAI                                    [Active] [•••] │ │
│  │ GPT-4, GPT-3.5-turbo                                   │ │
│  │ Last used: 2 hours ago                                 │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ Anthropic                              [Inactive] [•••] │ │
│  │ Claude-3 Opus, Sonnet, Haiku                           │ │
│  │ Not configured                                         │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ Google Gemini                          [Inactive] [•••] │ │
│  │ Gemini Pro, Gemini Pro Vision                          │ │
│  │ Not configured                                         │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  USAGE STATISTICS                                           │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ This Month: $12.50 saved vs. platform pricing         │ │
│  │ Total Tokens: 45,230                                   │ │
│  │ Average Cost per Optimization: $0.08                   │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## 🔄 User Flow Transitions

### Anonymous → Registered User
```
Trial Usage → Registration Prompt → Account Creation → Dashboard Onboarding
     ↓               ↓                    ↓                  ↓
  Track Usage    Show Benefits      Better-Auth Flow    Feature Tour
  (3 free uses)  (Unlimited)       (Email/Social)      (Guide)
```

### Free → Premium Upgrade
```
Usage Limit → Upgrade Prompt → Plan Selection → Payment → Premium Access
     ↓             ↓               ↓             ↓           ↓
  Hit Limit    Show Benefits   Compare Plans   Razorpay   Full Features
  (50/month)   (Unlimited)     (Pricing)       Payment    Activation
```

### Premium → BYOK Migration
```
Settings → API Keys → Provider Setup → Key Validation → Cost Savings
    ↓         ↓           ↓              ↓               ↓
 Account   Add Keys   Configure      Test Connection  Lower Costs
 Config    Interface  Providers      (Validation)     (Own Usage)
```

## 📱 Mobile User Experience

### Mobile-First Design Considerations
1. **Responsive Navigation**: Collapsible menu with touch-friendly targets
2. **Editor Adaptation**: Tabbed interface for LaTeX/Job Description/Preview
3. **Touch Optimization**: Larger buttons, swipe gestures, haptic feedback
4. **Offline Capability**: Service worker for basic functionality
5. **Progressive Web App**: Installable with native app experience

### Mobile User Journey
```
Mobile Landing → Try Editor (Tabs) → Mobile Dashboard → Touch-Optimized Settings
      ↓               ↓                    ↓                    ↓
  Swipe Hero     Tab Navigation      Card Layout         Touch Controls
  (Features)     (Editor/Preview)    (Recent Items)      (Settings)
```

## 🎯 Conversion Optimization Points

### Key Conversion Moments
1. **Landing → Trial**: Clear value proposition and no-signup trial
2. **Trial → Registration**: After 2nd use, show benefits clearly
3. **Free → Premium**: At usage limits, demonstrate premium value
4. **Premium → BYOK**: Cost savings calculator and setup assistance

### Optimization Strategies
1. **A/B Testing**: Different CTAs, pricing displays, feature highlights
2. **Personalization**: Industry-specific templates and examples
3. **Social Proof**: User testimonials, success stories, usage statistics
4. **Urgency**: Limited-time offers, usage counters, deadline reminders
5. **Simplification**: Reduce friction in signup and upgrade flows

## 📊 User Journey Analytics

### Key Metrics to Track
```typescript
interface UserJourneyMetrics {
  // Acquisition
  landingPageViews: number;
  trialStartRate: number;
  sourceAttribution: Record<string, number>;
  
  // Activation
  firstCompilationTime: number;
  trialCompletionRate: number;
  featureAdoptionRate: Record<string, number>;
  
  // Retention
  returnUserRate: number;
  sessionDuration: number;
  featureUsageFrequency: Record<string, number>;
  
  // Conversion
  trialToRegistrationRate: number;
  freeToPremuimRate: number;
  upgradeConversionTime: number;
  
  // Revenue
  monthlyRecurringRevenue: number;
  customerLifetimeValue: number;
  churnRate: number;
}
```

### Journey Optimization Tools
1. **Hotjar/FullStory**: User session recordings and heatmaps
2. **Google Analytics 4**: Enhanced ecommerce and conversion tracking
3. **Mixpanel**: Event-based user behavior analysis
4. **Amplitude**: Product analytics and cohort analysis
5. **Custom Analytics**: In-app usage tracking and feature adoption

This comprehensive user journey map ensures a smooth, conversion-optimized experience from anonymous visitor to paying customer, with clear paths for different user types and needs.
