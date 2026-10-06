# Privacy Policy

**Last reviewed: September 8, 2026**

This policy explains what Latexy collects, why it is used, where it may be sent,
and the choices available to you. It describes the service as it operates today;
it does not claim a privacy or security certification.

## 1. Information we process

### Account and billing data

When you create an account, we process your name, email address, profile image,
authentication records, verification status, and account preferences. If you use
social sign-in, the selected identity provider sends us the account information
you authorize. Password authentication is handled by Better Auth; Latexy does
not store a recoverable copy of your password.

Razorpay processes payment-card and mandate details. Latexy stores provider
identifiers, subscription state, plan, invoices/payment records, and related
billing metadata, but does not receive your full card number.

### Documents and feature data

We process the information you submit or create, including LaTeX source, résumés,
job descriptions, cover letters, application-tracker entries, comments, version
history, optimization requests and results, bibliographic data, and generated
PDFs or exports.

Résumé and job-description text is sensitive personal content. Do not include
information you do not want processed for the feature you select.

### Integrations and AI providers

When you deliberately use an AI feature, the prompt and document content needed
for that request is sent to the selected provider. Depending on your
configuration, that may be OpenAI, Anthropic, Google Gemini, or a compatible
endpoint configured by the service operator. With bring-your-own-key (BYOK),
Latexy decrypts and uses your stored key to make the request on your behalf;
the provider's own terms and privacy policy also apply.

If you connect Google or GitHub for sign-in, or enable GitHub, Dropbox, Zotero,
or Mendeley integrations, we process the authorization tokens, account
identifiers, and content needed for the actions you request. Disconnecting an
integration removes its stored Latexy credentials; it may not delete copies
already created at the provider.

Optional tools may send only the necessary query or text to services such as
LanguageTool, Crossref, and ORCID. URL-import features request the URL you
provide, which necessarily reveals a request from Latexy infrastructure to that
site.

### Technical, security, and usage data

We process IP addresses, user-agent/browser information, request identifiers,
authentication and security events, feature usage, job/compilation status,
errors, and performance measurements. Anonymous trial controls use bounded
device and network signals to enforce limits and prevent abuse.

The web application sends first-party Web Vitals and a small allow-listed set of
business events to the Latexy backend. Those events are recorded in service
metrics and structured logs. Latexy does not currently embed Google Analytics,
Mixpanel, Sentry, DataDog, advertising pixels, session replay, or keystroke
recording.

## 2. How we use information

We use information to:

- provide authentication, document editing, compilation, sharing, AI,
  collaboration, integrations, billing, and support;
- enforce plan and trial limits, prevent fraud and abuse, and secure the service;
- diagnose errors, measure reliability and performance, and improve features;
- send transactional messages and notifications you enable;
- meet legal obligations and respond to valid legal requests.

Latexy does not currently sell personal information or use it for
cross-context behavioral advertising.

## 3. Public sharing

Public share links and enabled portfolio pages can expose the résumé title and
content you choose to publish. Anonymous sharing attempts to redact detected
personal identifiers and does not release the original PDF while redaction is
pending, but automated redaction may not identify every sensitive detail. Review
content before sharing and revoke links or disable portfolio visibility when they
are no longer needed.

## 4. Service providers and disclosures

Latexy uses service providers to operate the product. Current infrastructure
includes Vercel (web hosting), Modal (API and worker compute), Neon
(PostgreSQL), Upstash (Redis), and Cloudflare R2 (object storage). Razorpay
handles payments, and Resend or a configured SMTP provider may deliver email.
The AI and optional integration providers described above receive data only when
their corresponding feature is used.

These providers process data under their own contracts and may operate in
different countries. We may also disclose information when required by law, to
protect users or the service, or as part of a merger, acquisition, financing, or
sale, subject to applicable safeguards and notice requirements.

## 5. Cookies and local browser storage

Latexy uses authentication and security cookies needed to sign you in and
protect requests. It also stores preferences such as light/dark and
high-contrast mode. Browser storage is used for items such as onboarding state,
offline drafts, pending offline work, and short-lived trace identifiers.

Latexy does not currently set advertising or third-party analytics cookies.
Blocking essential storage can prevent authentication, offline recovery, or
preferences from working.

## 6. Retention and deletion

Account records and saved documents are generally kept while your account is
active or until you delete the relevant item or request account deletion.
Short-lived job state and event replay data normally expires after about 24
hours. Temporary compilation files are cleaned automatically; generated
artifacts associated with saved work may remain until the owning record is
deleted and cleanup completes.

Security, billing, audit, and backup records may be retained longer when needed
for fraud prevention, financial recordkeeping, dispute resolution, recovery, or
legal obligations. Deletion from active systems may not immediately remove data
from limited-access backups or another provider you connected.

There is not currently a self-service account-deletion control. To request
account deletion or ask about a specific retention period, email
privacy@latexy.com from the address associated with your account.

## 7. Security

Latexy uses HTTPS in production, access controls, secret management, encrypted
storage for BYOK and supported integration credentials, bounded request and
upload controls, and automated dependency/security checks. No system is
completely secure, and these measures are not a guarantee against every
incident. Report a suspected security or privacy issue to privacy@latexy.com.

## 8. Your choices and rights

You can edit or delete individual résumés and other supported records, revoke
public share links, disable portfolio visibility, disconnect integrations,
remove BYOK credentials, and control available notification preferences.

Depending on where you live, applicable law may give you rights to access,
correct, delete, restrict, object to, or receive a portable copy of personal
information. To make a request, email privacy@latexy.com with the subject
“Privacy Rights Request”. We may need to verify your identity before acting.
You may also complain to the privacy or data-protection authority in your
jurisdiction.

## 9. Children

Latexy is not directed to children under 13 and does not knowingly collect their
personal information. If you believe a child has provided personal information,
contact privacy@latexy.com so the account and data can be reviewed.

## 10. Changes and contact

We may update this policy as the product, providers, or legal requirements
change. Material changes will be communicated through an appropriate in-product
or email notice, and the review date above will be updated.

Questions and privacy requests:

- Email: privacy@latexy.com
- Website: https://latexy.xyz

