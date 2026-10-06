import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Accessibility — Latexy',
  description: 'Latexy accessibility status, known limitations, and support contact.',
}

const reviewedOn = 'September 8, 2026'

export default function AccessibilityPage() {
  return (
    <div className="content-shell py-14 sm:py-20">
      <article className="mx-auto max-w-3xl">
        <p className="font-ui text-xs font-semibold uppercase tracking-[0.16em] text-accent-strong">
          Accessibility
        </p>
        <h1 className="mt-3 font-display text-4xl font-semibold tracking-tight text-fg sm:text-5xl">
          Building a résumé tool more people can use
        </h1>
        <p className="mt-5 text-lg leading-relaxed text-fg-2">
          Latexy is working toward an accessible editing, compilation, and sharing experience.
          This statement reports what is implemented today and names the gaps that remain; it is
          not a claim of WCAG conformance or certification.
        </p>

        <div className="mt-10 space-y-10 text-base leading-relaxed text-fg-2">
          <section aria-labelledby="current-support">
            <h2 id="current-support" className="font-display text-2xl font-semibold text-fg">
              Current support
            </h2>
            <ul className="mt-4 list-disc space-y-2 pl-6">
              <li>Semantic page landmarks, headings, form labels, and a keyboard skip link.</li>
              <li>Visible keyboard focus and keyboard-operated primary application workflows.</li>
              <li>Text alternatives for status, validation, loading, and recovery states.</li>
              <li>
                Light, dark, and enhanced high-contrast application modes, including automatic
                detection of the operating-system contrast preference.
              </li>
              <li>
                An Atkinson Hyperlegible document-font option in the résumé design panel.
              </li>
              <li>
                Readable HTML text alternatives on public share links and portfolio résumés.
              </li>
              <li>No session-recording or keystroke-capture SDKs on document surfaces.</li>
            </ul>
          </section>

          <section aria-labelledby="known-limitations">
            <h2 id="known-limitations" className="font-display text-2xl font-semibold text-fg">
              Known limitations
            </h2>
            <ul className="mt-4 list-disc space-y-2 pl-6">
              <li>
                Generated PDFs are not yet guaranteed to be tagged PDF/UA documents. Their text
                layer can be extracted, but that is not equivalent to a complete reading order and
                semantic structure.
              </li>
              <li>
                The Monaco source editor and embedded PDF viewer depend on browser and assistive-
                technology behavior outside our full control. Public output includes an HTML text
                alternative, but complex visual layout may not be represented in that text.
              </li>
              <li>
                Our named screen-reader test matrix is incomplete. We do not yet claim verified
                support for NVDA, VoiceOver, or TalkBack.
              </li>
            </ul>
          </section>

          <section aria-labelledby="support">
            <h2 id="support" className="font-display text-2xl font-semibold text-fg">
              Accessibility support
            </h2>
            <p className="mt-4">
              If an accessibility barrier prevents you from using Latexy, email{' '}
              <a
                className="font-semibold text-accent-strong underline underline-offset-4"
                href="mailto:support@latexy.com?subject=Accessibility%20support"
              >
                support@latexy.com
              </a>{' '}
              with “Accessibility” in the subject. Include the page, task, browser, and assistive
              technology if you can. We aim to acknowledge accessibility reports within two
              business days and will provide a practical workaround when one is available.
            </p>
          </section>

          <section aria-labelledby="testing">
            <h2 id="testing" className="font-display text-2xl font-semibold text-fg">
              Testing and updates
            </h2>
            <p className="mt-4">
              We combine automated accessibility checks, keyboard-only browser coverage, and manual
              review. We will update this page as screen-reader and output-format testing becomes
              reproducible. Last reviewed: {reviewedOn}.
            </p>
          </section>
        </div>
      </article>
    </div>
  )
}
