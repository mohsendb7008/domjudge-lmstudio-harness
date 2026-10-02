#include<iostream>
#include<algorithm>
#include<vector>
#include<set>
#include<climits>
#include<cmath>
#include<iomanip>
using namespace std;
typedef long long ll;

template <class T> int sgn(T x) { return (x > 0) - (x < 0); }
template<class T>
struct Point {
	typedef Point P;
	T x, y;
	explicit Point(T x=0, T y=0) : x(x), y(y) {}
	bool operator<(P p) const { return tie(x,y) < tie(p.x,p.y); }
	bool operator==(P p) const { return tie(x,y)==tie(p.x,p.y); }
	P operator+(P p) const { return P(x+p.x, y+p.y); }
	P operator-(P p) const { return P(x-p.x, y-p.y); }
	P operator*(T d) const { return P(x*d, y*d); }
	P operator/(T d) const { return P(x/d, y/d); }
	T dot(P p) const { return x*p.x + y*p.y; }
	T cross(P p) const { return x*p.y - y*p.x; }
	T cross(P a, P b) const { return (a-*this).cross(b-*this); }
	T dist2() const { return x*x + y*y; }
	T dist2(P o) const { return (o-*this).dist2(); }
	double dist() const { return sqrt((double)dist2()); }
	double dist(P o) const { return (o-*this).dist(); }
	// angle to x-axis in interval [-pi, pi]
	double angle() const { return atan2(y, x); }
	P unit() const { return *this/dist(); } // makes dist()=1
	P perp() const { return P(-y, x); } // rotates +90 degrees
	P normal() const { return perp().unit(); }
	// returns point rotated 'a' radians ccw around the origin
	P rotate(double a) const {
		return P(x*cos(a)-y*sin(a),x*sin(a)+y*cos(a)); }
	friend ostream& operator<<(ostream& os, P p) {
		return os << "(" << p.x << "," << p.y << ")"; }
};

typedef Point<ll> P;
pair<P, P> closest(vector<P> v) {
	set<P> S;
	sort(v.begin(), v.end(), [](P a, P b) { return a.y < b.y; });
	pair<ll, pair<P, P>> ret{LLONG_MAX, {P(), P()}};
	int j = 0;
	for (P p : v) {
		P d{1 + (ll)sqrt(ret.first), 0};
		while (v[j].y <= p.y - d.x) S.erase(v[j++]);
		auto lo = S.lower_bound(p - d), hi = S.upper_bound(p + d);
		for (; lo != hi; ++lo)
			ret = min(ret, {(*lo - p).dist2(), {*lo, p}});
		S.insert(p);
	}
	return ret.second;
}

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    int n; cin >> n;
    vector<P> pts(n);
    for(auto &p : pts)
        cin >> p.x >> p.y;
    auto neigh = closest(pts);
    vector<P> bef, aft;
    for(int i = 0; i < n; ++i) {
        if(pts[i] == neigh.first) continue;
        if(pts[i] == neigh.second) continue;
        if(pts[i].dist2(neigh.first) <
            pts[i].dist2(neigh.second))
            bef.push_back(pts[i]);
        else aft.push_back(pts[i]);
    }
    sort(bef.rbegin(), bef.rend(), [&](const P& A, const P& B) {
        return A.dist2(neigh.first) < B.dist2(neigh.first);
    });
    sort(aft.rbegin(), aft.rend(), [&](const P& A, const P& B) {
        return A.dist2(neigh.second) < B.dist2(neigh.second);
    });
    double sm = 0.0;
    for(int i = 1; i < bef.size(); ++i)
        sm += bef[i - 1].dist(bef[i]);
    if(bef.size() > 0)
        sm += bef.back().dist(neigh.first);
    sm += neigh.first.dist(neigh.second);
    if(aft.size() > 0)
        sm += aft.back().dist(neigh.second);
    for(int i = 1; i < aft.size(); ++i)
        sm += aft[i - 1].dist(aft[i]);
    cout << setprecision(15);
    cout << sm << '\n';
}
