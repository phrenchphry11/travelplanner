import { SignIn } from "@clerk/clerk-react";

export default function SignInPage() {
  return (
    <main className="page centered">
      <SignIn routing="path" path="/sign-in" signUpUrl="/sign-up" />
    </main>
  );
}
