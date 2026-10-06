/**
 * B55 UI localisation contract.
 *
 * This is deliberately separate from document/translation locales. `Locale`
 * controls Latexy's chrome only; resume translation continues to use the
 * closed document-language contract in the workspace feature.
 */
export const UI_LOCALES = ['en', 'hi', 'mr', 'te', 'pa', 'bn'] as const
export type UiLocale = (typeof UI_LOCALES)[number]

export const UI_LOCALE_LABELS: Record<UiLocale, string> = {
  en: 'English',
  hi: 'हिन्दी',
  mr: 'मराठी',
  te: 'తెలుగు',
  pa: 'ਪੰਜਾਬੀ',
  bn: 'বাংলা',
}

const englishMessages = {
  'a11y.skipToContent': 'Skip to content',
  'nav.platform': 'Platform',
  'nav.templates': 'Templates',
  'nav.pricing': 'Pricing',
  'nav.resources': 'Resources',
  'nav.faq': 'FAQ',
  'nav.dashboard': 'Dashboard',
  'nav.workspace': 'Workspace',
  'nav.tracker': 'Tracker',
  'nav.studio': 'Studio',
  'nav.billing': 'Billing',
  'nav.developerApi': 'Developer API',
  'nav.aiProviders': 'AI Providers',
  'nav.settings': 'Settings',
  'nav.admin': 'Admin',
  'nav.privacy': 'Privacy',
  'nav.terms': 'Terms',
  'nav.account': 'Account',
  'nav.closeAccountMenu': 'Close account menu',
  'nav.openAccountMenu': 'Open account menu',
  'nav.closeNavigationMenu': 'Close navigation menu',
  'nav.openNavigationMenu': 'Open navigation menu',
  'nav.menu': 'Menu',
  'nav.close': 'Close',
  'nav.logIn': 'Log In',
  'nav.tryFree': 'Try Free',
  'nav.signOut': 'Sign Out',
  'nav.signingOut': 'Signing out…',
  'nav.install': 'Install',
  'nav.installLatexy': 'Install Latexy',
  'locale.label': 'Language',
  'locale.uiLanguage': 'Interface language',
  'locale.documentLanguageHint': 'This changes the interface only, not your resume language.',
  'auth.welcomeBack': 'Welcome back',
  'auth.signInContinue': 'Sign in to continue to your workspace.',
  'auth.noAccount': "Don't have an account?",
  'auth.createAccount': 'Create account',
  'auth.setResumeRight': 'Set your résumé right.',
  'auth.alreadyAccount': 'Already have an account?',
  'auth.signUp': 'Sign up',
  'auth.signIn': 'Sign In',
  'auth.email': 'Email',
  'auth.fullName': 'Full Name',
  'auth.password': 'Password',
  'auth.confirmPassword': 'Confirm Password',
  'auth.forgotPassword': 'Forgot password?',
  'auth.atLeastEight': 'At least 8 characters.',
  'auth.passwordMismatch': 'Passwords do not match.',
  'auth.orEmail': 'or continue with email',
  'auth.orSignUpEmail': 'or sign up with email',
  'auth.redirecting': 'Redirecting…',
  'auth.passkey': 'Sign in with a passkey',
  'auth.waitingPasskey': 'Waiting for passkey…',
  'auth.passkeyHint': 'Your browser or security key will verify the credential without exposing your email.',
  'auth.signInRequired': 'Sign in required',
  'auth.signInRequiredDescription': 'Please sign in to access your workspace and resumes.',
  'auth.continueToLogin': 'Continue to Login',
  'workspace.label': 'Workspace',
  'workspace.resumeLibrary': 'Resume Library',
  'workspace.description': 'Create, edit, and optimize resumes from a single workspace.',
  'workspace.newResume': 'New Resume',
  'workspace.searchContent': 'Search content',
  'workspace.runHistory': 'Run History',
  'workspace.matchToJob': 'Match to Job',
  'workspace.export': 'Export',
  'workspace.noResumes': 'No resumes found',
  'workspace.noSearchResults': 'No results for “{{query}}”.',
  'workspace.createFirst': 'Create your first resume to start your pipeline.',
  'workspace.createResume': 'Create Resume',
  'workspace.today': 'Today',
  'workspace.updatedDays': 'Updated {{count}} day ago',
  'workspace.updatedDays_plural': 'Updated {{count}} days ago',
  'workspace.resumeCount': '{{count}} resume',
  'workspace.resumeCount_plural': '{{count}} resumes',
  'workspace.documentLanguage': 'Document language',
  'workspace.documentLanguageDescription': 'Choose the language of resume content separately from this interface language.',
  'onboarding.gettingStarted': 'Getting started',
  'onboarding.skip': 'Skip',
  'onboarding.back': 'Back',
  'onboarding.next': 'Next',
  'onboarding.welcomeTitle': 'Welcome to Latexy',
  'onboarding.welcomeDescription': 'Your AI-powered resume optimization platform',
  'onboarding.workflowTitle': 'How Latexy works',
  'onboarding.workflowDescription': 'Three simple steps to a tailored resume',
  'onboarding.createFirst': 'Create my first resume',
  'onboarding.skipExplore': 'Skip and explore on my own',
} as const

export type UiMessageKey = keyof typeof englishMessages

// Every supported locale has the same key set. Keeping these translations in
// source (instead of runtime machine translation) makes coverage auditable.
export const UI_MESSAGES: Record<UiLocale, Record<UiMessageKey, string>> = {
  en: englishMessages,
  hi: {
    ...englishMessages,
    'a11y.skipToContent': 'सामग्री पर जाएँ', 'nav.platform': 'प्लेटफ़ॉर्म', 'nav.templates': 'टेम्पलेट', 'nav.pricing': 'मूल्य', 'nav.resources': 'संसाधन', 'nav.faq': 'सामान्य प्रश्न', 'nav.dashboard': 'डैशबोर्ड', 'nav.workspace': 'वर्कस्पेस', 'nav.tracker': 'ट्रैकर', 'nav.studio': 'स्टूडियो', 'nav.billing': 'बिलिंग', 'nav.developerApi': 'डेवलपर API', 'nav.aiProviders': 'AI प्रदाता', 'nav.settings': 'सेटिंग्स', 'nav.admin': 'एडमिन', 'nav.privacy': 'गोपनीयता', 'nav.terms': 'शर्तें', 'nav.account': 'खाता', 'nav.closeAccountMenu': 'खाता मेनू बंद करें', 'nav.openAccountMenu': 'खाता मेनू खोलें', 'nav.closeNavigationMenu': 'नेविगेशन मेनू बंद करें', 'nav.openNavigationMenu': 'नेविगेशन मेनू खोलें', 'nav.menu': 'मेनू', 'nav.close': 'बंद करें', 'nav.logIn': 'लॉग इन', 'nav.tryFree': 'मुफ़्त आज़माएँ', 'nav.signOut': 'साइन आउट', 'nav.signingOut': 'साइन आउट हो रहा है…', 'nav.install': 'इंस्टॉल करें', 'nav.installLatexy': 'Latexy इंस्टॉल करें', 'locale.label': 'भाषा', 'locale.uiLanguage': 'इंटरफ़ेस भाषा', 'locale.documentLanguageHint': 'यह केवल इंटरफ़ेस बदलता है, आपके रिज़्यूमे की भाषा नहीं।', 'auth.welcomeBack': 'वापसी पर स्वागत है', 'auth.signInContinue': 'अपने वर्कस्पेस पर जाने के लिए साइन इन करें।', 'auth.noAccount': 'खाता नहीं है?', 'auth.createAccount': 'खाता बनाएँ', 'auth.setResumeRight': 'अपना रिज़्यूमे सही बनाएँ।', 'auth.alreadyAccount': 'पहले से खाता है?', 'auth.signUp': 'साइन अप', 'auth.signIn': 'साइन इन', 'auth.email': 'ईमेल', 'auth.fullName': 'पूरा नाम', 'auth.password': 'पासवर्ड', 'auth.confirmPassword': 'पासवर्ड की पुष्टि करें', 'auth.forgotPassword': 'पासवर्ड भूल गए?', 'auth.atLeastEight': 'कम से कम 8 अक्षर।', 'auth.passwordMismatch': 'पासवर्ड मेल नहीं खाते।', 'auth.orEmail': 'या ईमेल से जारी रखें', 'auth.orSignUpEmail': 'या ईमेल से साइन अप करें', 'auth.redirecting': 'रीडायरेक्ट हो रहा है…', 'auth.passkey': 'पासकी से साइन इन करें', 'auth.waitingPasskey': 'पासकी की प्रतीक्षा…', 'auth.passkeyHint': 'आपका ब्राउज़र या सुरक्षा कुंजी ईमेल साझा किए बिना क्रेडेंशियल की पुष्टि करेगी।', 'auth.signInRequired': 'साइन इन आवश्यक है', 'auth.signInRequiredDescription': 'अपने वर्कस्पेस और रिज़्यूमे के लिए साइन इन करें।', 'auth.continueToLogin': 'लॉग इन जारी रखें', 'workspace.label': 'वर्कस्पेस', 'workspace.resumeLibrary': 'रिज़्यूमे लाइब्रेरी', 'workspace.description': 'एक ही वर्कस्पेस से रिज़्यूमे बनाएँ, संपादित करें और बेहतर करें।', 'workspace.newResume': 'नया रिज़्यूमे', 'workspace.searchContent': 'सामग्री खोजें', 'workspace.runHistory': 'रन इतिहास', 'workspace.matchToJob': 'नौकरी से मिलाएँ', 'workspace.export': 'एक्सपोर्ट', 'workspace.noResumes': 'कोई रिज़्यूमे नहीं मिला', 'workspace.noSearchResults': '“{{query}}” के लिए कोई परिणाम नहीं।', 'workspace.createFirst': 'शुरुआत करने के लिए अपना पहला रिज़्यूमे बनाएँ।', 'workspace.createResume': 'रिज़्यूमे बनाएँ', 'workspace.today': 'आज', 'workspace.updatedDays': 'पिछले {{count}} दिन में अपडेट', 'workspace.updatedDays_plural': 'पिछले {{count}} दिनों में अपडेट', 'workspace.resumeCount': '{{count}} रिज़्यूमे', 'workspace.resumeCount_plural': '{{count}} रिज़्यूमे', 'workspace.documentLanguage': 'दस्तावेज़ की भाषा', 'workspace.documentLanguageDescription': 'रिज़्यूमे की सामग्री की भाषा इस इंटरफ़ेस भाषा से अलग चुनें।',
  },
  mr: {
    ...englishMessages,
    'a11y.skipToContent': 'सामग्रीकडे जा', 'nav.platform': 'प्लॅटफॉर्म', 'nav.templates': 'टेम्पलेट्स', 'nav.pricing': 'किंमत', 'nav.resources': 'संसाधने', 'nav.faq': 'वारंवार विचारले जाणारे प्रश्न', 'nav.dashboard': 'डॅशबोर्ड', 'nav.workspace': 'वर्कस्पेस', 'nav.tracker': 'ट्रॅकर', 'nav.studio': 'स्टुडिओ', 'nav.billing': 'बिलिंग', 'nav.developerApi': 'डेव्हलपर API', 'nav.aiProviders': 'AI प्रदाते', 'nav.settings': 'सेटिंग्ज', 'nav.admin': 'अॅडमिन', 'nav.privacy': 'गोपनीयता', 'nav.terms': 'अटी', 'nav.account': 'खाते', 'nav.closeAccountMenu': 'खाते मेनू बंद करा', 'nav.openAccountMenu': 'खाते मेनू उघडा', 'nav.closeNavigationMenu': 'नेव्हिगेशन मेनू बंद करा', 'nav.openNavigationMenu': 'नेव्हिगेशन मेनू उघडा', 'nav.menu': 'मेनू', 'nav.close': 'बंद करा', 'nav.logIn': 'लॉग इन', 'nav.tryFree': 'मोफत वापरून पाहा', 'nav.signOut': 'साइन आउट', 'nav.signingOut': 'साइन आउट होत आहे…', 'nav.install': 'इन्स्टॉल करा', 'nav.installLatexy': 'Latexy इन्स्टॉल करा', 'locale.label': 'भाषा', 'locale.uiLanguage': 'इंटरफेस भाषा', 'locale.documentLanguageHint': 'यामुळे फक्त इंटरफेस बदलतो, तुमच्या रिझ्युमेची भाषा नाही।', 'auth.welcomeBack': 'पुन्हा स्वागत आहे', 'auth.signInContinue': 'तुमच्या वर्कस्पेसमध्ये जाण्यासाठी साइन इन करा.', 'auth.noAccount': 'खाते नाही?', 'auth.createAccount': 'खाते तयार करा', 'auth.setResumeRight': 'तुमचा रिझ्युमे योग्य बनवा.', 'auth.alreadyAccount': 'आधीच खाते आहे?', 'auth.signUp': 'साइन अप', 'auth.signIn': 'साइन इन', 'auth.email': 'ईमेल', 'auth.fullName': 'पूर्ण नाव', 'auth.password': 'पासवर्ड', 'auth.confirmPassword': 'पासवर्डची पुष्टी करा', 'auth.forgotPassword': 'पासवर्ड विसरलात?', 'auth.atLeastEight': 'किमान ८ अक्षरे.', 'auth.passwordMismatch': 'पासवर्ड जुळत नाहीत.', 'auth.orEmail': 'किंवा ईमेलने सुरू ठेवा', 'auth.orSignUpEmail': 'किंवा ईमेलने साइन अप करा', 'auth.redirecting': 'पुढे पाठवत आहे…', 'auth.passkey': 'पासकीने साइन इन करा', 'auth.waitingPasskey': 'पासकीची प्रतीक्षा…', 'auth.passkeyHint': 'तुमचा ब्राउझर किंवा सुरक्षा की ईमेल उघड न करता क्रेडेन्शियल तपासेल.', 'auth.signInRequired': 'साइन इन आवश्यक', 'auth.signInRequiredDescription': 'वर्कस्पेस आणि रिझ्युमेसाठी साइन इन करा.', 'auth.continueToLogin': 'लॉग इन सुरू ठेवा', 'workspace.label': 'वर्कस्पेस', 'workspace.resumeLibrary': 'रिझ्युमे लायब्ररी', 'workspace.description': 'एकाच वर्कस्पेसमधून रिझ्युमे तयार, संपादित आणि सुधारित करा.', 'workspace.newResume': 'नवीन रिझ्युमे', 'workspace.searchContent': 'सामग्री शोधा', 'workspace.runHistory': 'रन इतिहास', 'workspace.matchToJob': 'नोकरीशी जुळवा', 'workspace.export': 'एक्सपोर्ट', 'workspace.noResumes': 'रिझ्युमे सापडले नाहीत', 'workspace.noSearchResults': '“{{query}}” साठी निकाल नाहीत.', 'workspace.createFirst': 'सुरू करण्यासाठी तुमचा पहिला रिझ्युमे तयार करा.', 'workspace.createResume': 'रिझ्युमे तयार करा', 'workspace.today': 'आज', 'workspace.updatedDays': '{{count}} दिवसांपूर्वी अपडेट', 'workspace.updatedDays_plural': '{{count}} दिवसांपूर्वी अपडेट', 'workspace.resumeCount': '{{count}} रिझ्युमे', 'workspace.resumeCount_plural': '{{count}} रिझ्युमे', 'workspace.documentLanguage': 'दस्तऐवजाची भाषा', 'workspace.documentLanguageDescription': 'रिझ्युमेची सामग्रीची भाषा या इंटरफेस भाषेपासून स्वतंत्र निवडा.',
  },
  te: {
    ...englishMessages,
    'a11y.skipToContent': 'విషయానికి వెళ్లండి', 'nav.platform': 'ప్లాట్‌ఫారమ్', 'nav.templates': 'టెంప్లేట్లు', 'nav.pricing': 'ధరలు', 'nav.resources': 'వనరులు', 'nav.faq': 'తరచుగా అడిగే ప్రశ్నలు', 'nav.dashboard': 'డ్యాష్‌బోర్డ్', 'nav.workspace': 'వర్క్‌స్పేస్', 'nav.tracker': 'ట్రాకర్', 'nav.studio': 'స్టూడియో', 'nav.billing': 'బిల్లింగ్', 'nav.developerApi': 'డెవలపర్ API', 'nav.aiProviders': 'AI ప్రొవైడర్లు', 'nav.settings': 'సెట్టింగ్స్', 'nav.admin': 'అడ్మిన్', 'nav.privacy': 'గోప్యత', 'nav.terms': 'నిబంధనలు', 'nav.account': 'ఖాతా', 'nav.closeAccountMenu': 'ఖాతా మెనూను మూసివేయండి', 'nav.openAccountMenu': 'ఖాతా మెనూను తెరవండి', 'nav.closeNavigationMenu': 'నావిగేషన్ మెనూను మూసివేయండి', 'nav.openNavigationMenu': 'నావిగేషన్ మెనూను తెరవండి', 'nav.menu': 'మెనూ', 'nav.close': 'మూసివేయండి', 'nav.logIn': 'లాగిన్', 'nav.tryFree': 'ఉచితంగా ప్రయత్నించండి', 'nav.signOut': 'సైన్ అవుట్', 'nav.signingOut': 'సైన్ అవుట్ అవుతోంది…', 'nav.install': 'ఇన్‌స్టాల్', 'nav.installLatexy': 'Latexyని ఇన్‌స్టాల్ చేయండి', 'locale.label': 'భాష', 'locale.uiLanguage': 'ఇంటర్‌ఫేస్ భాష', 'locale.documentLanguageHint': 'ఇది ఇంటర్‌ఫేస్‌ను మాత్రమే మారుస్తుంది, మీ రెజ్యూమే భాషను కాదు.', 'auth.welcomeBack': 'తిరిగి స్వాగతం', 'auth.signInContinue': 'మీ వర్క్‌స్పేస్‌కు వెళ్లడానికి సైన్ ఇన్ చేయండి.', 'auth.noAccount': 'ఖాతా లేదా?', 'auth.createAccount': 'ఖాతా సృష్టించండి', 'auth.setResumeRight': 'మీ రెజ్యూమేను మెరుగుపరచండి.', 'auth.alreadyAccount': 'ఇప్పటికే ఖాతా ఉందా?', 'auth.signUp': 'సైన్ అప్', 'auth.signIn': 'సైన్ ఇన్', 'auth.email': 'ఇమెయిల్', 'auth.fullName': 'పూర్తి పేరు', 'auth.password': 'పాస్‌వర్డ్', 'auth.confirmPassword': 'పాస్‌వర్డ్‌ను నిర్ధారించండి', 'auth.forgotPassword': 'పాస్‌వర్డ్ మర్చిపోయారా?', 'auth.atLeastEight': 'కనీసం 8 అక్షరాలు.', 'auth.passwordMismatch': 'పాస్‌వర్డ్‌లు సరిపోలలేదు.', 'auth.orEmail': 'లేదా ఇమెయిల్‌తో కొనసాగండి', 'auth.orSignUpEmail': 'లేదా ఇమెయిల్‌తో సైన్ అప్ చేయండి', 'auth.redirecting': 'దారి మళ్లిస్తోంది…', 'auth.passkey': 'పాస్‌కీతో సైన్ ఇన్ చేయండి', 'auth.waitingPasskey': 'పాస్‌కీ కోసం వేచి ఉంది…', 'auth.passkeyHint': 'మీ బ్రౌజర్ లేదా భద్రతా కీ మీ ఇమెయిల్‌ను బహిర్గతం చేయకుండా ఆధారాన్ని నిర్ధారిస్తుంది.', 'auth.signInRequired': 'సైన్ ఇన్ అవసరం', 'auth.signInRequiredDescription': 'మీ వర్క్‌స్పేస్ మరియు రెజ్యూమేలను చూడటానికి సైన్ ఇన్ చేయండి.', 'auth.continueToLogin': 'లాగిన్ కొనసాగించండి', 'workspace.label': 'వర్క్‌స్పేస్', 'workspace.resumeLibrary': 'రెజ్యూమే లైబ్రరీ', 'workspace.description': 'ఒకే వర్క్‌స్పేస్ నుండి రెజ్యూమేలను సృష్టించండి, సవరించండి, మెరుగుపరచండి.', 'workspace.newResume': 'కొత్త రెజ్యూమే', 'workspace.searchContent': 'కంటెంట్ వెతకండి', 'workspace.runHistory': 'రన్ చరిత్ర', 'workspace.matchToJob': 'ఉద్యోగంతో సరిపోల్చండి', 'workspace.export': 'ఎగుమతి', 'workspace.noResumes': 'రెజ్యూమేలు కనబడలేదు', 'workspace.noSearchResults': '“{{query}}” కోసం ఫలితాలు లేవు.', 'workspace.createFirst': 'ప్రారంభించడానికి మీ మొదటి రెజ్యూమేను సృష్టించండి.', 'workspace.createResume': 'రెజ్యూమే సృష్టించండి', 'workspace.today': 'ఈ రోజు', 'workspace.updatedDays': '{{count}} రోజుల క్రితం నవీకరించబడింది', 'workspace.updatedDays_plural': '{{count}} రోజుల క్రితం నవీకరించబడింది', 'workspace.resumeCount': '{{count}} రెజ్యూమే', 'workspace.resumeCount_plural': '{{count}} రెజ్యూమేలు', 'workspace.documentLanguage': 'డాక్యుమెంట్ భాష', 'workspace.documentLanguageDescription': 'రెజ్యూమే కంటెంట్ భాషను ఈ ఇంటర్‌ఫేస్ భాషకు వేరుగా ఎంచుకోండి.',
  },
  pa: {
    ...englishMessages,
    'a11y.skipToContent': 'ਸਮੱਗਰੀ ’ਤੇ ਜਾਓ', 'nav.platform': 'ਪਲੇਟਫਾਰਮ', 'nav.templates': 'ਟੈਂਪਲੇਟ', 'nav.pricing': 'ਕੀਮਤ', 'nav.resources': 'ਸਰੋਤ', 'nav.faq': 'ਆਮ ਸਵਾਲ', 'nav.dashboard': 'ਡੈਸ਼ਬੋਰਡ', 'nav.workspace': 'ਵਰਕਸਪੇਸ', 'nav.tracker': 'ਟ੍ਰੈਕਰ', 'nav.studio': 'ਸਟੂਡੀਓ', 'nav.billing': 'ਬਿਲਿੰਗ', 'nav.developerApi': 'ਡਿਵੈਲਪਰ API', 'nav.aiProviders': 'AI ਪ੍ਰਦਾਤਾ', 'nav.settings': 'ਸੈਟਿੰਗਾਂ', 'nav.admin': 'ਐਡਮਿਨ', 'nav.privacy': 'ਪਰਦੇਦਾਰੀ', 'nav.terms': 'ਸ਼ਰਤਾਂ', 'nav.account': 'ਖਾਤਾ', 'nav.closeAccountMenu': 'ਖਾਤਾ ਮੀਨੂ ਬੰਦ ਕਰੋ', 'nav.openAccountMenu': 'ਖਾਤਾ ਮੀਨੂ ਖੋਲ੍ਹੋ', 'nav.closeNavigationMenu': 'ਨੇਵੀਗੇਸ਼ਨ ਮੀਨੂ ਬੰਦ ਕਰੋ', 'nav.openNavigationMenu': 'ਨੇਵੀਗੇਸ਼ਨ ਮੀਨੂ ਖੋਲ੍ਹੋ', 'nav.menu': 'ਮੀਨੂ', 'nav.close': 'ਬੰਦ ਕਰੋ', 'nav.logIn': 'ਲੌਗ ਇਨ', 'nav.tryFree': 'ਮੁਫ਼ਤ ਅਜ਼ਮਾਓ', 'nav.signOut': 'ਸਾਈਨ ਆਊਟ', 'nav.signingOut': 'ਸਾਈਨ ਆਊਟ ਹੋ ਰਿਹਾ ਹੈ…', 'nav.install': 'ਇੰਸਟਾਲ', 'nav.installLatexy': 'Latexy ਇੰਸਟਾਲ ਕਰੋ', 'locale.label': 'ਭਾਸ਼ਾ', 'locale.uiLanguage': 'ਇੰਟਰਫੇਸ ਭਾਸ਼ਾ', 'locale.documentLanguageHint': 'ਇਹ ਸਿਰਫ਼ ਇੰਟਰਫੇਸ ਬਦਲਦਾ ਹੈ, ਤੁਹਾਡੇ ਰਿਜ਼ਿਊਮੇ ਦੀ ਭਾਸ਼ਾ ਨਹੀਂ।', 'auth.welcomeBack': 'ਮੁੜ ਸਵਾਗਤ ਹੈ', 'auth.signInContinue': 'ਆਪਣੇ ਵਰਕਸਪੇਸ ਵਿੱਚ ਜਾਣ ਲਈ ਸਾਈਨ ਇਨ ਕਰੋ।', 'auth.noAccount': 'ਖਾਤਾ ਨਹੀਂ ਹੈ?', 'auth.createAccount': 'ਖਾਤਾ ਬਣਾਓ', 'auth.setResumeRight': 'ਆਪਣਾ ਰਿਜ਼ਿਊਮੇ ਠੀਕ ਬਣਾਓ।', 'auth.alreadyAccount': 'ਪਹਿਲਾਂ ਹੀ ਖਾਤਾ ਹੈ?', 'auth.signUp': 'ਸਾਈਨ ਅਪ', 'auth.signIn': 'ਸਾਈਨ ਇਨ', 'auth.email': 'ਈਮੇਲ', 'auth.fullName': 'ਪੂਰਾ ਨਾਮ', 'auth.password': 'ਪਾਸਵਰਡ', 'auth.confirmPassword': 'ਪਾਸਵਰਡ ਦੀ ਪੁਸ਼ਟੀ ਕਰੋ', 'auth.forgotPassword': 'ਪਾਸਵਰਡ ਭੁੱਲ ਗਏ?', 'auth.atLeastEight': 'ਘੱਟੋ-ਘੱਟ 8 ਅੱਖਰ।', 'auth.passwordMismatch': 'ਪਾਸਵਰਡ ਮੇਲ ਨਹੀਂ ਖਾਂਦੇ।', 'auth.orEmail': 'ਜਾਂ ਈਮੇਲ ਨਾਲ ਜਾਰੀ ਰੱਖੋ', 'auth.orSignUpEmail': 'ਜਾਂ ਈਮੇਲ ਨਾਲ ਸਾਈਨ ਅਪ ਕਰੋ', 'auth.redirecting': 'ਰੀਡਾਇਰੈਕਟ ਹੋ ਰਿਹਾ ਹੈ…', 'auth.passkey': 'ਪਾਸਕੀ ਨਾਲ ਸਾਈਨ ਇਨ ਕਰੋ', 'auth.waitingPasskey': 'ਪਾਸਕੀ ਦੀ ਉਡੀਕ…', 'auth.passkeyHint': 'ਤੁਹਾਡਾ ਬ੍ਰਾਊਜ਼ਰ ਜਾਂ ਸੁਰੱਖਿਆ ਕੁੰਜੀ ਈਮੇਲ ਦਿਖਾਏ ਬਿਨਾਂ ਪ੍ਰਮਾਣ ਪੱਕਾ ਕਰੇਗੀ।', 'auth.signInRequired': 'ਸਾਈਨ ਇਨ ਲੋੜੀਂਦਾ ਹੈ', 'auth.signInRequiredDescription': 'ਆਪਣੇ ਵਰਕਸਪੇਸ ਅਤੇ ਰਿਜ਼ਿਊਮੇ ਲਈ ਸਾਈਨ ਇਨ ਕਰੋ।', 'auth.continueToLogin': 'ਲੌਗ ਇਨ ਜਾਰੀ ਰੱਖੋ', 'workspace.label': 'ਵਰਕਸਪੇਸ', 'workspace.resumeLibrary': 'ਰਿਜ਼ਿਊਮੇ ਲਾਇਬ੍ਰੇਰੀ', 'workspace.description': 'ਇੱਕੋ ਵਰਕਸਪੇਸ ਤੋਂ ਰਿਜ਼ਿਊਮੇ ਬਣਾਓ, ਸੋਧੋ ਅਤੇ ਸੁਧਾਰੋ।', 'workspace.newResume': 'ਨਵਾਂ ਰਿਜ਼ਿਊਮੇ', 'workspace.searchContent': 'ਸਮੱਗਰੀ ਖੋਜੋ', 'workspace.runHistory': 'ਰਨ ਇਤਿਹਾਸ', 'workspace.matchToJob': 'ਨੌਕਰੀ ਨਾਲ ਮਿਲਾਓ', 'workspace.export': 'ਐਕਸਪੋਰਟ', 'workspace.noResumes': 'ਕੋਈ ਰਿਜ਼ਿਊਮੇ ਨਹੀਂ ਮਿਲਿਆ', 'workspace.noSearchResults': '“{{query}}” ਲਈ ਕੋਈ ਨਤੀਜਾ ਨਹੀਂ।', 'workspace.createFirst': 'ਸ਼ੁਰੂ ਕਰਨ ਲਈ ਆਪਣਾ ਪਹਿਲਾ ਰਿਜ਼ਿਊਮੇ ਬਣਾਓ।', 'workspace.createResume': 'ਰਿਜ਼ਿਊਮੇ ਬਣਾਓ', 'workspace.today': 'ਅੱਜ', 'workspace.updatedDays': '{{count}} ਦਿਨ ਪਹਿਲਾਂ ਅੱਪਡੇਟ', 'workspace.updatedDays_plural': '{{count}} ਦਿਨ ਪਹਿਲਾਂ ਅੱਪਡੇਟ', 'workspace.resumeCount': '{{count}} ਰਿਜ਼ਿਊਮੇ', 'workspace.resumeCount_plural': '{{count}} ਰਿਜ਼ਿਊਮੇ', 'workspace.documentLanguage': 'ਦਸਤਾਵੇਜ਼ ਦੀ ਭਾਸ਼ਾ', 'workspace.documentLanguageDescription': 'ਰਿਜ਼ਿਊਮੇ ਦੀ ਸਮੱਗਰੀ ਦੀ ਭਾਸ਼ਾ ਇਸ ਇੰਟਰਫੇਸ ਭਾਸ਼ਾ ਤੋਂ ਵੱਖ ਚੁਣੋ।',
  },
  bn: {
    ...englishMessages,
    'a11y.skipToContent': 'বিষয়বস্তুতে যান', 'nav.platform': 'প্ল্যাটফর্ম', 'nav.templates': 'টেমপ্লেট', 'nav.pricing': 'মূল্য', 'nav.resources': 'রিসোর্স', 'nav.faq': 'সাধারণ প্রশ্ন', 'nav.dashboard': 'ড্যাশবোর্ড', 'nav.workspace': 'ওয়ার্কস্পেস', 'nav.tracker': 'ট্র্যাকার', 'nav.studio': 'স্টুডিও', 'nav.billing': 'বিলিং', 'nav.developerApi': 'ডেভেলপার API', 'nav.aiProviders': 'AI প্রদানকারী', 'nav.settings': 'সেটিংস', 'nav.admin': 'অ্যাডমিন', 'nav.privacy': 'গোপনীয়তা', 'nav.terms': 'শর্তাবলি', 'nav.account': 'অ্যাকাউন্ট', 'nav.closeAccountMenu': 'অ্যাকাউন্ট মেনু বন্ধ করুন', 'nav.openAccountMenu': 'অ্যাকাউন্ট মেনু খুলুন', 'nav.closeNavigationMenu': 'নেভিগেশন মেনু বন্ধ করুন', 'nav.openNavigationMenu': 'নেভিগেশন মেনু খুলুন', 'nav.menu': 'মেনু', 'nav.close': 'বন্ধ করুন', 'nav.logIn': 'লগ ইন', 'nav.tryFree': 'বিনামূল্যে চেষ্টা করুন', 'nav.signOut': 'সাইন আউট', 'nav.signingOut': 'সাইন আউট হচ্ছে…', 'nav.install': 'ইনস্টল', 'nav.installLatexy': 'Latexy ইনস্টল করুন', 'locale.label': 'ভাষা', 'locale.uiLanguage': 'ইন্টারফেসের ভাষা', 'locale.documentLanguageHint': 'এটি শুধু ইন্টারফেস বদলায়, আপনার রিজিউমের ভাষা নয়।', 'auth.welcomeBack': 'আবার স্বাগতম', 'auth.signInContinue': 'আপনার ওয়ার্কস্পেসে যেতে সাইন ইন করুন।', 'auth.noAccount': 'অ্যাকাউন্ট নেই?', 'auth.createAccount': 'অ্যাকাউন্ট তৈরি করুন', 'auth.setResumeRight': 'আপনার রিজিউমে ঠিকভাবে তৈরি করুন।', 'auth.alreadyAccount': 'ইতিমধ্যে অ্যাকাউন্ট আছে?', 'auth.signUp': 'সাইন আপ', 'auth.signIn': 'সাইন ইন', 'auth.email': 'ইমেল', 'auth.fullName': 'পুরো নাম', 'auth.password': 'পাসওয়ার্ড', 'auth.confirmPassword': 'পাসওয়ার্ড নিশ্চিত করুন', 'auth.forgotPassword': 'পাসওয়ার্ড ভুলে গেছেন?', 'auth.atLeastEight': 'কমপক্ষে ৮টি অক্ষর।', 'auth.passwordMismatch': 'পাসওয়ার্ড মেলেনি।', 'auth.orEmail': 'অথবা ইমেল দিয়ে চালিয়ে যান', 'auth.orSignUpEmail': 'অথবা ইমেল দিয়ে সাইন আপ করুন', 'auth.redirecting': 'রিডাইরেক্ট হচ্ছে…', 'auth.passkey': 'পাসকি দিয়ে সাইন ইন করুন', 'auth.waitingPasskey': 'পাসকির অপেক্ষা…', 'auth.passkeyHint': 'আপনার ব্রাউজার বা নিরাপত্তা কী ইমেল প্রকাশ না করে প্রমাণপত্র যাচাই করবে।', 'auth.signInRequired': 'সাইন ইন প্রয়োজন', 'auth.signInRequiredDescription': 'আপনার ওয়ার্কস্পেস ও রিজিউমে দেখতে সাইন ইন করুন।', 'auth.continueToLogin': 'লগ ইন চালিয়ে যান', 'workspace.label': 'ওয়ার্কস্পেস', 'workspace.resumeLibrary': 'রিজিউমে লাইব্রেরি', 'workspace.description': 'একটি ওয়ার্কস্পেস থেকে রিজিউমে তৈরি, সম্পাদনা ও উন্নত করুন।', 'workspace.newResume': 'নতুন রিজিউমে', 'workspace.searchContent': 'বিষয়বস্তু খুঁজুন', 'workspace.runHistory': 'রান ইতিহাস', 'workspace.matchToJob': 'চাকরির সঙ্গে মেলান', 'workspace.export': 'এক্সপোর্ট', 'workspace.noResumes': 'কোনও রিজিউমে পাওয়া যায়নি', 'workspace.noSearchResults': '“{{query}}”-এর জন্য কোনও ফল নেই।', 'workspace.createFirst': 'শুরু করতে আপনার প্রথম রিজিউমে তৈরি করুন।', 'workspace.createResume': 'রিজিউমে তৈরি করুন', 'workspace.today': 'আজ', 'workspace.updatedDays': '{{count}} দিন আগে আপডেট', 'workspace.updatedDays_plural': '{{count}} দিন আগে আপডেট', 'workspace.resumeCount': '{{count}}টি রিজিউমে', 'workspace.resumeCount_plural': '{{count}}টি রিজিউমে', 'workspace.documentLanguage': 'ডকুমেন্টের ভাষা', 'workspace.documentLanguageDescription': 'রিজিউমের বিষয়বস্তুর ভাষা এই ইন্টারফেসের ভাষা থেকে আলাদা করে বেছে নিন।',
  },
}

// Onboarding is kept as a small explicit override block so its coverage is
// easy to review independently from the larger navigation catalog above.
const ONBOARDING_MESSAGES: Record<UiLocale, Record<string, string>> = {
  en: { 'onboarding.gettingStarted': 'Getting started', 'onboarding.skip': 'Skip', 'onboarding.back': 'Back', 'onboarding.next': 'Next', 'onboarding.welcomeTitle': 'Welcome to Latexy', 'onboarding.welcomeDescription': 'Your AI-powered resume optimization platform', 'onboarding.workflowTitle': 'How Latexy works', 'onboarding.workflowDescription': 'Three simple steps to a tailored resume', 'onboarding.createFirst': 'Create my first resume', 'onboarding.skipExplore': 'Skip and explore on my own' },
  hi: { 'onboarding.gettingStarted': 'शुरू करें', 'onboarding.skip': 'छोड़ें', 'onboarding.back': 'वापस', 'onboarding.next': 'आगे', 'onboarding.welcomeTitle': 'Latexy में आपका स्वागत है', 'onboarding.welcomeDescription': 'AI-संचालित रिज़्यूमे सुधार प्लेटफ़ॉर्म', 'onboarding.workflowTitle': 'Latexy कैसे काम करता है', 'onboarding.workflowDescription': 'बेहतर रिज़्यूमे के लिए तीन आसान चरण', 'onboarding.createFirst': 'मेरा पहला रिज़्यूमे बनाएँ', 'onboarding.skipExplore': 'छोड़ें और अपने तरीके से देखें' },
  mr: { 'onboarding.gettingStarted': 'सुरुवात करा', 'onboarding.skip': 'वगळा', 'onboarding.back': 'मागे', 'onboarding.next': 'पुढे', 'onboarding.welcomeTitle': 'Latexy मध्ये स्वागत आहे', 'onboarding.welcomeDescription': 'AI-सक्षम रिझ्युमे सुधारणा प्लॅटफॉर्म', 'onboarding.workflowTitle': 'Latexy कसे काम करते', 'onboarding.workflowDescription': 'सुधारित रिझ्युमेसाठी तीन सोप्या पायऱ्या', 'onboarding.createFirst': 'माझा पहिला रिझ्युमे तयार करा', 'onboarding.skipExplore': 'वगळा आणि स्वतः पाहा' },
  te: { 'onboarding.gettingStarted': 'ప్రారంభం', 'onboarding.skip': 'దాటవేయండి', 'onboarding.back': 'వెనుకకు', 'onboarding.next': 'తదుపరి', 'onboarding.welcomeTitle': 'Latexyకి స్వాగతం', 'onboarding.welcomeDescription': 'AI ఆధారిత రెజ్యూమే మెరుగుదల వేదిక', 'onboarding.workflowTitle': 'Latexy ఎలా పనిచేస్తుంది', 'onboarding.workflowDescription': 'మెరుగైన రెజ్యూమే కోసం మూడు సులభమైన దశలు', 'onboarding.createFirst': 'నా మొదటి రెజ్యూమేను సృష్టించండి', 'onboarding.skipExplore': 'దాటవేసి స్వయంగా చూడండి' },
  pa: { 'onboarding.gettingStarted': 'ਸ਼ੁਰੂਆਤ', 'onboarding.skip': 'ਛੱਡੋ', 'onboarding.back': 'ਪਿੱਛੇ', 'onboarding.next': 'ਅੱਗੇ', 'onboarding.welcomeTitle': 'Latexy ਵਿੱਚ ਜੀ ਆਇਆਂ ਨੂੰ', 'onboarding.welcomeDescription': 'AI-ਸੰਚਾਲਿਤ ਰਿਜ਼ਿਊਮੇ ਸੁਧਾਰ ਪਲੇਟਫਾਰਮ', 'onboarding.workflowTitle': 'Latexy ਕਿਵੇਂ ਕੰਮ ਕਰਦਾ ਹੈ', 'onboarding.workflowDescription': 'ਬਿਹਤਰ ਰਿਜ਼ਿਊਮੇ ਲਈ ਤਿੰਨ ਸੌਖੇ ਕਦਮ', 'onboarding.createFirst': 'ਮੇਰਾ ਪਹਿਲਾ ਰਿਜ਼ਿਊਮੇ ਬਣਾਓ', 'onboarding.skipExplore': 'ਛੱਡੋ ਅਤੇ ਆਪਣੇ ਤਰੀਕੇ ਨਾਲ ਵੇਖੋ' },
  bn: { 'onboarding.gettingStarted': 'শুরু করুন', 'onboarding.skip': 'এড়িয়ে যান', 'onboarding.back': 'পিছনে', 'onboarding.next': 'পরবর্তী', 'onboarding.welcomeTitle': 'Latexy-তে স্বাগতম', 'onboarding.welcomeDescription': 'AI-চালিত রিজিউমে উন্নতির প্ল্যাটফর্ম', 'onboarding.workflowTitle': 'Latexy কীভাবে কাজ করে', 'onboarding.workflowDescription': 'আরও ভালো রিজিউমের জন্য তিনটি সহজ ধাপ', 'onboarding.createFirst': 'আমার প্রথম রিজিউমে তৈরি করুন', 'onboarding.skipExplore': 'এড়িয়ে নিজের মতো দেখুন' },
}
for (const locale of UI_LOCALES) Object.assign(UI_MESSAGES[locale], ONBOARDING_MESSAGES[locale])

export function normalizeUiLocale(value: string | null | undefined): UiLocale {
  return parseUiLocale(value) ?? 'en'
}

function parseUiLocale(value: string | null | undefined): UiLocale | null {
  const base = (value ?? '').toLowerCase().split('-')[0]
  return (UI_LOCALES as readonly string[]).includes(base) ? (base as UiLocale) : null
}

export function negotiateUiLocale(cookieValue: string | null | undefined, acceptLanguage: string | null | undefined): UiLocale {
  const persisted = parseUiLocale(cookieValue)
  if (persisted) return persisted
  for (const part of (acceptLanguage ?? '').split(',')) {
    const candidate = part.trim().split(';')[0]
    const locale = parseUiLocale(candidate)
    if (locale) return locale
  }
  return 'en'
}

export function formatUiMessage(locale: UiLocale, key: UiMessageKey, values?: Record<string, string | number>): string {
  const template = UI_MESSAGES[locale][key] ?? UI_MESSAGES.en[key]
  return template.replace(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g, (_, name: string) => {
    const value = values?.[name]
    return value === undefined || value === null ? `{{${name}}}` : String(value)
  })
}

export function formatUiPlural(locale: UiLocale, key: 'workspace.updatedDays' | 'workspace.resumeCount', count: number): string {
  const pluralKey = count === 1 ? key : `${key}_plural`
  return formatUiMessage(locale, pluralKey as UiMessageKey, { count })
}
