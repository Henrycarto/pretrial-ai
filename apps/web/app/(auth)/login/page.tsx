import Link from "next/link";

export const metadata = { title: "Sign in" };

/**
 * SMART on FHIR sign in.
 *
 * This page is UI only. The authorisation code exchange, token storage, and
 * session handling are not built. The button below does not start a real
 * launch, and the page says so rather than presenting a dead control that
 * looks live.
 *
 * What is decided and encoded here is the launch shape: an EHR launch and a
 * standalone launch are the two entry points a hospital integration uses,
 * and the issuer field is what a standalone launch needs from the operator.
 * The route lives under (auth) so it renders without the application chrome.
 */
export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-md">
        <div className="mb-6">
          <div className="font-mono text-sm tracking-tight text-ink">
            Pretrial<span className="text-accent">.ai</span>
          </div>
          <div className="label-micro mt-1">feasibility instrument</div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <span className="label-micro">sign in</span>
            <span className="label-micro">SMART on FHIR</span>
          </div>

          <div className="space-y-4 p-5">
            <div>
              <label className="label-micro mb-1.5 block" htmlFor="issuer">
                FHIR issuer
              </label>
              <input
                id="issuer"
                className="field-mono"
                defaultValue="https://launch.smarthealthit.org/v/r4/fhir"
                readOnly
              />
              <p className="mt-1.5 text-xs text-ink-dim">
                The base URL of the FHIR server that authorises the launch.
              </p>
            </div>

            <button type="button" disabled className="btn btn-primary w-full">
              launch authorisation
            </button>

            <div className="border border-signal-warn/50 bg-signal-warn/[0.06] px-3 py-2.5">
              <div className="label-micro mb-1 text-signal-warn">not implemented</div>
              <p className="text-xs leading-relaxed text-ink-muted">
                The SMART on FHIR authorisation flow is not built. The local stack
                runs without authentication, and every service is reachable
                directly. Do not deploy this outside a private network.
              </p>
            </div>
          </div>

          <div className="border-t border-edge bg-surface-sunken px-5 py-3">
            <Link href="/dashboard" className="btn btn-secondary w-full">
              continue without signing in
            </Link>
          </div>
        </div>

        <p className="mt-4 text-xs text-ink-dim">
          Scopes the production flow will request: launch, openid, fhirUser,
          offline_access, patient/*.read
        </p>
      </div>
    </div>
  );
}
