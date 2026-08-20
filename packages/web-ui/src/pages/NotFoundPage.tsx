import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";

export function NotFoundPage(): React.JSX.Element {
  return (
    <div className="container mx-auto p-12 text-center">
      <h1 className="text-3xl font-semibold">404</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        The page you're looking for doesn't exist.
      </p>
      <Button asChild className="mt-6">
        <Link to="/persons">Go to persons</Link>
      </Button>
    </div>
  );
}