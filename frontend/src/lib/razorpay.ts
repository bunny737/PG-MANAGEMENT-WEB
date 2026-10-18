// Razorpay Checkout for platform subscription billing (PRD §4). Resident rent never goes
// through Razorpay, so this is only ever used for the owner's own plan payment.

const CHECKOUT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

interface CheckoutOptions {
  key: string;
  subscription_id: string;
  name: string;
  description?: string;
  prefill?: { name?: string; email?: string; contact?: string };
  theme?: { color?: string };
  handler: () => void;
  modal: { ondismiss: () => void };
}

interface RazorpayInstance {
  open: () => void;
}

declare global {
  interface Window {
    Razorpay?: new (options: CheckoutOptions) => RazorpayInstance;
  }
}

let loading: Promise<void> | null = null;

function loadCheckoutScript(): Promise<void> {
  if (typeof window === "undefined") return Promise.reject(new Error("Checkout needs a browser"));
  if (window.Razorpay) return Promise.resolve();
  if (!loading) {
    loading = new Promise<void>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = CHECKOUT_SRC;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => {
        script.remove();
        loading = null; // allow a retry after a network failure
        reject(new Error("Could not load Razorpay Checkout"));
      };
      document.body.appendChild(script);
    });
  }
  return loading;
}

export interface SubscriptionCheckout {
  keyId: string;
  subscriptionId: string;
  businessName: string;
  description?: string;
  prefill?: CheckoutOptions["prefill"];
}

/**
 * Opens Checkout for an existing Razorpay subscription. Resolves "paid" once the owner has
 * authorised the payment, or "dismissed" if they closed the popup. "paid" is not activation:
 * the plan only activates when Razorpay's webhook reaches the server, so callers should
 * re-read the subscription rather than trusting this result.
 */
export async function openSubscriptionCheckout(checkout: SubscriptionCheckout): Promise<"paid" | "dismissed"> {
  await loadCheckoutScript();
  const Razorpay = window.Razorpay;
  if (!Razorpay) throw new Error("Razorpay Checkout is unavailable");

  return new Promise((resolve) => {
    new Razorpay({
      key: checkout.keyId,
      subscription_id: checkout.subscriptionId,
      name: checkout.businessName,
      description: checkout.description,
      prefill: checkout.prefill,
      handler: () => resolve("paid"),
      modal: { ondismiss: () => resolve("dismissed") },
    }).open();
  });
}
