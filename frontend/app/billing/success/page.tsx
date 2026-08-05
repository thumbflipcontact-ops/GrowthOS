export default function BillingSuccessPage() {
  return (
    <div className="container">
      <h1>You&apos;re all set</h1>
      <div className="card">
        <p>Your trial has started. Next, connect an account so GrowthOS has something to work with.</p>
        <a href="/settings/plugins" className="btn">
          Connect an account
        </a>
      </div>
      <p className="muted">
        <a href="/dashboard">Go to dashboard</a>
      </p>
    </div>
  );
}
