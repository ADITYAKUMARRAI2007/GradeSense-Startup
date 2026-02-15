import { useState, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { 
  GraduationCap, 
  LayoutDashboard, 
  Upload, 
  FileText, 
  BarChart3, 
  Lightbulb, 
  Users, 
  BookOpen,
  ClipboardList,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronDown,
  ChevronUp,
  Bell,
  MessageSquare,
  Menu,
  X,
  Search,
  Shield
} from "lucide-react";
import { Button } from "./ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "./ui/avatar";
import { Sheet, SheetContent, SheetTrigger } from "./ui/sheet";
import { cn } from "../lib/utils";
import axios from "axios";
import { API } from "../App";
import GlobalSearch from "./GlobalSearch";
import NotificationDropdown from "./NotificationDropdown";
import GlobalGradingProgress from "./GlobalGradingProgress";
import FeedbackBeacon from "./FeedbackBeacon";

const teacherNavItems = [
  { icon: LayoutDashboard, label: "Dashboard", path: "/teacher/dashboard" },
  { icon: Upload, label: "Upload & Grade", path: "/teacher/upload" },
  { icon: FileText, label: "Review Papers", path: "/teacher/review" },
  { 
    icon: BarChart3, 
    label: "Analytics", 
    isGroup: true,
    children: [
      { icon: BarChart3, label: "Ask AI", path: "/teacher/analytics" },
      { icon: BarChart3, label: "Class Reports", path: "/teacher/reports" },
    ]
  },
  { 
    icon: Settings, 
    label: "Manage", 
    isGroup: true,
    children: [
      { icon: ClipboardList, label: "Manage Exams", path: "/teacher/exams" },
      { icon: BookOpen, label: "Manage Batches", path: "/teacher/batches" },
      { icon: Users, label: "Manage Students", path: "/teacher/students" },
    ]
  },
  { icon: MessageSquare, label: "Re-evaluations", path: "/teacher/re-evaluations" },
];

const studentNavItems = [
  { icon: LayoutDashboard, label: "My Dashboard", path: "/student/dashboard" },
  { icon: BookOpen, label: "My Exams", path: "/student/exams" },
  { icon: FileText, label: "My Results", path: "/student/results" },
  { icon: MessageSquare, label: "Request Re-evaluation", path: "/student/re-evaluation" },
];

export default function Layout({ children, user }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState({});
  const [searchOpen, setSearchOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  const navItems = user?.role === "student" ? studentNavItems : teacherNavItems;

  // Keyboard shortcut for search (Ctrl+K or Cmd+K)
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const handleLogout = async () => {
    try {
      await axios.post(`${API}/auth/logout`);
    } catch (error) {
      console.error("Logout error:", error);
    }
    window.location.href = "/login";
  };

  const toggleGroup = (label) => {
    setExpandedGroups(prev => ({
      ...prev,
      [label]: !prev[label]
    }));
  };

  const isGroupActive = (item) => {
    if (!item.children) return false;
    return item.children.some(child => location.pathname === child.path);
  };

  const NavContent = ({ isMobile = false }) => (
    <>
      {/* Logo */}
      <div className={cn(
        "flex items-center gap-3 h-16 border-b",
        isMobile ? "px-4" : "px-4"
      )}>
        <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary">
          <GraduationCap className="w-6 h-6 text-white" />
        </div>
        {(isMobile || !collapsed) && (
          <span className="text-xl font-bold text-foreground">
            Grade<span className="text-primary">Sense</span>
          </span>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex flex-col gap-1 p-3 mt-2 flex-1">
        {navItems.map((item, idx) => {
          const Icon = item.icon;
          
          if (item.isGroup) {
            const isExpanded = expandedGroups[item.label];
            const hasActiveChild = isGroupActive(item);
            
            return (
              <div key={idx}>
                {/* Group Header */}
                <button
                  onClick={() => toggleGroup(item.label)}
                  className={cn(
                    "w-full flex items-center justify-between px-3 py-2.5 rounded-lg transition-all",
                    hasActiveChild
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                  data-testid={`nav-group-${item.label.toLowerCase()}`}
                >
                  <div className="flex items-center gap-3">
                    <Icon className="w-5 h-5 flex-shrink-0" />
                    {(isMobile || !collapsed) && <span className="font-medium">{item.label}</span>}
                  </div>
                  {(isMobile || !collapsed) && (
                    isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />
                  )}
                </button>

                {/* Group Children */}
                {isExpanded && (isMobile || !collapsed) && (
                  <div className="ml-4 mt-1 space-y-1">
                    {item.children.map((child) => {
                      const ChildIcon = child.icon;
                      const isActive = location.pathname === child.path;
                      
                      return (
                        <Link
                          key={child.path}
                          to={child.path}
                          onClick={() => isMobile && setMobileOpen(false)}
                          data-testid={`nav-${child.label.toLowerCase().replace(/\s+/g, '-')}`}
                          className={cn(
                            "flex items-center gap-3 px-3 py-2 rounded-lg transition-all text-sm",
                            isActive 
                              ? "bg-primary text-white shadow-md shadow-orange-500/20" 
                              : "text-muted-foreground hover:bg-muted hover:text-foreground"
                          )}
                        >
                          <ChildIcon className="w-4 h-4 flex-shrink-0" />
                          <span className="font-medium">{child.label}</span>
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          }
          
          // Regular item
          const isActive = location.pathname === item.path;
          
          return (
            <Link
              key={item.path}
              to={item.path}
              onClick={() => isMobile && setMobileOpen(false)}
              data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, '-')}`}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all",
                isActive 
                  ? "bg-primary text-white shadow-md shadow-orange-500/20" 
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <Icon className="w-5 h-5 flex-shrink-0" />
              {(isMobile || !collapsed) && <span className="font-medium">{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Bottom section */}
      <div className="p-3 border-t mt-auto">
        {/* Admin Panel Link - Only for admins/teachers */}
        {user?.role === "teacher" && (
          <Link
            to="/admin"
            onClick={() => isMobile && setMobileOpen(false)}
            data-testid="nav-admin-panel"
            className={cn(
              "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all mb-1",
              location.pathname.startsWith("/admin")
                ? "bg-gradient-to-r from-orange-500 to-red-500 text-white shadow-lg" 
                : "text-muted-foreground hover:bg-muted hover:text-foreground border border-orange-200 hover:border-orange-300"
            )}
          >
            <Shield className="w-5 h-5 flex-shrink-0" />
            {(isMobile || !collapsed) && (
              <div className="flex items-center gap-2 flex-1">
                <span className="font-medium">Admin Panel</span>
                {location.pathname.startsWith("/admin") && (
                  <span className="ml-auto w-2 h-2 bg-white rounded-full animate-pulse"></span>
                )}
              </div>
            )}
          </Link>
        )}
        
        <Link
          to="/settings"
          onClick={() => isMobile && setMobileOpen(false)}
          data-testid="nav-settings"
          className={cn(
            "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all",
            location.pathname === "/settings" 
              ? "bg-primary text-white" 
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          )}
        >
          <Settings className="w-5 h-5 flex-shrink-0" />
          {(isMobile || !collapsed) && <span className="font-medium">Settings</span>}
        </Link>
        
        <Button
          variant="ghost"
          onClick={handleLogout}
          className="w-full justify-start gap-3 px-3 py-2.5 mt-1 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
          data-testid="logout-btn"
        >
          <LogOut className="w-5 h-5 flex-shrink-0" />
          {(isMobile || !collapsed) && <span className="font-medium">Logout</span>}
        </Button>
      </div>
    </>
  );

  return (
    <div className="flex min-h-screen bg-muted/30">
      {/* Desktop Sidebar */}
      <aside 
        className={cn(
          "fixed left-0 top-0 z-40 h-screen bg-white border-r border-border transition-all duration-300 hidden lg:flex flex-col",
          collapsed ? "w-[72px]" : "w-[260px]"
        )}
        data-testid="sidebar"
      >
        <NavContent />
        
        {/* Collapse button - Desktop only */}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setCollapsed(!collapsed)}
          className="absolute -right-3 top-20 w-6 h-6 rounded-full bg-white border shadow-sm hover:bg-muted"
          data-testid="collapse-sidebar-btn"
        >
          <ChevronLeft className={cn("w-4 h-4 transition-transform", collapsed && "rotate-180")} />
        </Button>
      </aside>

      {/* Mobile Sidebar (Sheet) */}
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="p-0 w-[280px] flex flex-col">
          <NavContent isMobile />
        </SheetContent>
      </Sheet>

      {/* Main content */}
      <div className={cn(
        "flex-1 transition-all duration-300",
        "lg:ml-[260px]",
        collapsed && "lg:ml-[72px]"
      )}>
        {/* Header */}
        <header className="sticky top-0 z-30 flex items-center justify-between h-14 lg:h-16 px-4 lg:px-6 bg-white border-b">
          <div className="flex items-center gap-3">
            {/* Mobile menu button */}
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden"
              onClick={() => setMobileOpen(true)}
              data-testid="mobile-menu-btn"
            >
              <Menu className="w-5 h-5" />
            </Button>
            
            <h1 className="text-base lg:text-lg font-semibold text-foreground truncate">
              {navItems.find(item => item.path === location.pathname)?.label || "GradeSense"}
            </h1>
          </div>
          
          <div className="flex items-center gap-2 lg:gap-4">
            {/* Search Button */}
            <Button 
              variant="ghost" 
              size="icon"
              onClick={() => setSearchOpen(true)}
              className="hidden md:flex"
              data-testid="search-btn"
            >
              <Search className="w-5 h-5" />
            </Button>

            {/* Notifications */}
            <NotificationDropdown user={user} />

            {/* User */}
            <div className="flex items-center gap-2 lg:gap-3">
              <Avatar className="w-8 h-8 lg:w-9 lg:h-9">
                <AvatarImage src={user?.picture} alt={user?.name} />
                <AvatarFallback className="bg-primary text-white text-sm">
                  {user?.name?.charAt(0) || "U"}
                </AvatarFallback>
              </Avatar>
              <div className="hidden md:block">
                <p className="text-sm font-medium">{user?.name}</p>
                <p className="text-xs text-muted-foreground capitalize">{user?.role}</p>
              </div>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="p-4 lg:p-6">
          {children}
        </main>
      </div>

      {/* Global Search Modal */}
      <GlobalSearch open={searchOpen} onClose={() => setSearchOpen(false)} user={user} />
      
      {/* Global Grading Progress Indicator */}
      <GlobalGradingProgress />
      
      {/* Feedback Beacon */}
      <FeedbackBeacon user={user} />
    </div>
  );
}
