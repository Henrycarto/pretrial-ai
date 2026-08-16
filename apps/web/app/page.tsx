import Link from "next/link";

import { FidelityScoreBadge } from "@/components/fidelity/FidelityScoreBadge";

/**
 * Landing page.
 *
 * The opening sentence is the first text on the page. There is no navigation
 * bar, no wordmark, and no chrome above it, which is a deliberate ordering
 * decision: the claim is the product, and a visitor who reads nothing else
 * should read that.
 *
 * The rest of the page is laid out as a specification sheet rather than as a
 * marketing page. Services are rows in a table, capabilities are stated with
 * the statistic that backs them, and the one visual element is the same
 * FidelityScoreBadge the application uses. Nothing here is decorative.
 */
export default function LandingPage() {
  return (
    <div className="min-h-screen">
      <section className="border-b border-edge px-6 py-16 sm:px-10 lg:px-16">
        <div className="mx-auto max-w-5xl">
          <p className="max-w-3xl text-2xl leading-snug text-ink sm:text-[28px]">
            Clinical trial recruitment takes{" "}
            <span className="tabular text-accent-bright">18 months</span> on average.
            Pretrial.ai compresses feasibility to{" "}
            <span className="tabular text-accent-bright">48 hours</span>.
          </p>

          <div className="mt-10 flex flex-wrap items-center gap-6">
            <div className="font-mono text-sm tracking-tight text-ink">
              Pretrial<span className="text-accent">.ai</span>
            </div>
            <div className="h-4 w-px bg-edge-strong" aria-hidden />
            <p className="text-sm text-ink-muted">
              Feasibility on statistically validated synthetic patient cohorts.
            </p>
          </div>

          <div className="mt-8 flex flex-wrap gap-2">
            <Link href="/cohorts/new" className="btn btn-primary">
              build a cohort
            </Link>
            <Link href="/dashboard" className="btn btn-secondary">
              open dashboard
            </Link>
          </div>
        </div>
      </section>

      <section className="border-b border-edge px-6 py-12 sm:px-10 lg:px-16">
        <div className="mx-auto grid max-w-5xl gap-10 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <div>
            <div className="label-micro mb-4">the problem</div>
            <p className="max-w-2xl text-[15px] leading-relaxed text-ink-muted">
              A sponsor cannot know whether a protocol recruits until sites have
              screened real patients against it. That answer arrives months into
              a study, after the sites are contracted and the budget is committed.
              When the answer is no, the protocol is amended and the clock restarts.
            </p>
            <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-ink-muted">
              A synthetic cohort that reproduces the real population&apos;s
              distributions, comorbidity structure, and lab value correlations
              answers the same question before the first site is opened. The only
              thing that makes it worth trusting is proof that it matches, which
              is why validation is a first class service here and not a footnote.
            </p>
          </div>

          <div className="flex flex-col items-center gap-3 border border-edge bg-surface px-8 py-7">
            <FidelityScoreBadge score={94.7} size="lg" />
            <p className="max-w-[15rem] text-center text-xs leading-relaxed text-ink-dim">
              The single figure a clinical operations director reads to decide
              whether a cohort is usable. Above 90 it is. Below 70 it is not.
            </p>
          </div>
        </div>
      </section>

      <section className="border-b border-edge px-6 py-12 sm:px-10 lg:px-16">
        <div className="mx-auto max-w-5xl">
          <div className="label-micro mb-5">services</div>
          <div className="overflow-x-auto border border-edge">
            <table className="data-table">
              <thead>
                <tr>
                  <th>service</th>
                  <th>function</th>
                  <th>method</th>
                  <th className="text-right">port</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="font-mono text-[13px] text-ink">SyntheCore</td>
                  <td className="text-ink-muted">
                    Generates a synthetic cohort from seed data and screens it
                    against the protocol&apos;s criteria.
                  </td>
                  <td className="font-mono text-xs text-ink-dim">
                    CTGAN, conditional sampling
                  </td>
                  <td className="tabular text-right text-ink-dim">8001</td>
                </tr>
                <tr>
                  <td className="font-mono text-[13px] text-ink">FidelityCheck</td>
                  <td className="text-ink-muted">
                    Proves the synthetic cohort matches the reference population,
                    or shows exactly where it does not.
                  </td>
                  <td className="font-mono text-xs text-ink-dim">
                    KS, Jensen-Shannon, correlation delta
                  </td>
                  <td className="tabular text-right text-ink-dim">8002</td>
                </tr>
                <tr>
                  <td className="font-mono text-[13px] text-ink">FHIR-Link</td>
                  <td className="text-ink-muted">
                    Emits the validated cohort as FHIR R4 bundles a hospital
                    network or CTMS can ingest.
                  </td>
                  <td className="font-mono text-xs text-ink-dim">
                    R4 Patient and Observation, HTEST tagged
                  </td>
                  <td className="tabular text-right text-ink-dim">8003</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="px-6 py-12 sm:px-10 lg:px-16">
        <div className="mx-auto max-w-5xl">
          <div className="label-micro mb-5">what the score is made of</div>
          <dl className="grid grid-cols-1 gap-px border border-edge bg-edge sm:grid-cols-3">
            <Metric
              term="marginal agreement"
              weight="0.40"
              body="Two sample Kolmogorov-Smirnov per continuous feature, total variation distance per categorical feature. This is what inclusion criteria are written against."
            />
            <Metric
              term="shape agreement"
              weight="0.35"
              body="Jensen-Shannon divergence across the full support, base 2. Catches a distribution that occupies the right range with the wrong shape."
            />
            <Metric
              term="dependency structure"
              weight="0.25"
              body="Correlation matrix comparison. Catches a generator that reproduced every variable alone and lost the relationships between them."
            />
          </dl>

          <p className="mt-6 max-w-3xl text-sm leading-relaxed text-ink-muted">
            The weights are published because the number has to survive scrutiny
            from a biostatistician who did not build it. The full method is in{" "}
            <span className="font-mono text-ink">
              docs/synthetic-data-methodology.md
            </span>
            .
          </p>
        </div>
      </section>

      <footer className="border-t border-edge px-6 py-6 sm:px-10 lg:px-16">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-4">
          <span className="font-mono text-xs text-ink-dim">Pretrial.ai</span>
          <span className="text-xs text-ink-dim">
            Synthetic cohorts are tagged as test health data on export. They are
            not patient records.
          </span>
        </div>
      </footer>
    </div>
  );
}

function Metric({
  term,
  weight,
  body,
}: {
  term: string;
  weight: string;
  body: string;
}) {
  return (
    <div className="bg-surface px-4 py-4">
      <div className="flex items-baseline justify-between">
        <dt className="label-micro">{term}</dt>
        <span className="tabular text-xs text-accent-bright">{weight}</span>
      </div>
      <dd className="mt-2.5 text-sm leading-relaxed text-ink-muted">{body}</dd>
    </div>
  );
}
