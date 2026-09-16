import { SignUp } from "@clerk/clerk-react";

export default function SignUpPage() {
  return (
    <main className="page centered">
      <SignUp routing="path" path="/sign-up" signInUrl="/sign-in" />
    </main>
  );
}
