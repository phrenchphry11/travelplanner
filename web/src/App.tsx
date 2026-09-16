import { RedirectToSignIn, SignedIn, SignedOut } from "@clerk/clerk-react";
import { Navigate, Route, Routes } from "react-router-dom";
import NewTrip from "./pages/NewTrip";
import SignInPage from "./pages/SignIn";
import SignUpPage from "./pages/SignUp";
import TripBoard from "./pages/TripBoard";
import TripList from "./pages/TripList";

function Protected({ children }: { children: React.ReactNode }) {
  return (
    <>
      <SignedIn>{children}</SignedIn>
      <SignedOut>
        <RedirectToSignIn />
      </SignedOut>
    </>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/sign-in/*" element={<SignInPage />} />
      <Route path="/sign-up/*" element={<SignUpPage />} />
      <Route path="/trips" element={<Protected><TripList /></Protected>} />
      <Route path="/trips/new" element={<Protected><NewTrip /></Protected>} />
      <Route path="/trips/:tripId" element={<Protected><TripBoard /></Protected>} />
      <Route path="*" element={<Navigate to="/trips" replace />} />
    </Routes>
  );
}
