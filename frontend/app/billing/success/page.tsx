export default function BillingSuccessPage() {
  return (
    <div className="container">
      <h1>You&apos;re all set</h1>
      <div className="card">
        <p>Your subscription is active. Head to your dashboard to keep finding leads.</p>
        <a href="/dashboard" className="btn">
          Go to dashboard
        </a>
      </div>
    </div>
  );
}
