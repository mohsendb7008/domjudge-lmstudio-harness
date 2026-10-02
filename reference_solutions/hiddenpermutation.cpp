#include<iostream>
#include<sstream>
#include<cassert>
#include<vector>
#include<cmath>
using namespace std;
#define rep(i,a,b) for(auto i = (a); i < (b); ++i)
typedef long long ll;

const double EPS = 1e-9;

void bail() {
    cout << "impossible\n";
    exit(0);
}

struct intx {
  intx() { normalize(1); }
  intx(string n) { init(n); }
  intx(int n) { stringstream ss; ss << n; init(ss.str()); }
  intx(const intx& other)
    : sign(other.sign), data(other.data) { }
  int sign;
  vector<unsigned int> data;
  static const int dcnt = 9;
  static const unsigned int radix = 1000000000U;
  int size() const { return data.size(); }
  void init(string n) {
    intx res; res.data.clear();
    if (n.empty()) n = "0";
    if (n[0] == '-') res.sign = -1, n = n.substr(1);
    for (int i = n.size() - 1; i >= 0; i -= intx::dcnt) {
      unsigned int digit = 0;
      for (int j = intx::dcnt - 1; j >= 0; j--) {
        int idx = i - j;
        if (idx < 0) continue;
        digit = digit * 10 + (n[idx] - '0'); }
      res.data.push_back(digit); }
    data = res.data;
    normalize(res.sign); }
  intx& normalize(int nsign) {
    if (data.empty()) data.push_back(0);
    for (int i = data.size() - 1; i > 0 && data[i] == 0; i--)
      data.erase(data.begin() + i);
    sign = data.size() == 1 && data[0] == 0 ? 1 : nsign;
    return *this; }
  friend ostream& operator <<(ostream& outs, const intx& n) {
    if (n.sign < 0) outs << '-';
    bool first = true;
    for (int i = n.size() - 1; i >= 0; i--) {
      if (first) outs << n.data[i], first = false;
      else {
        unsigned int cur = n.data[i];
        stringstream ss; ss << cur;
        string s = ss.str();
        int len = s.size();
        while (len < intx::dcnt) outs << '0', len++;
        outs << s; } }
    return outs; }
  string to_string() const {
    stringstream ss; ss << *this; return ss.str(); }
  bool operator <(const intx& b) const {
    if (sign != b.sign) return sign < b.sign;
    if (size() != b.size())
      return sign == 1 ? size() < b.size() : size() > b.size();
    for (int i = size() - 1; i >= 0; i--)
      if (data[i] != b.data[i])
        return sign == 1 ? data[i] < b.data[i]
                         : data[i] > b.data[i];
    return false; }
  intx operator -() const {
    intx res(*this); res.sign *= -1; return res; }
  friend intx abs(const intx &n) { return n < 0 ? -n : n; }
  intx operator +(const intx& b) const {
    if (sign > 0 && b.sign < 0) return *this - (-b);
    if (sign < 0 && b.sign > 0) return b - (-*this);
    if (sign < 0 && b.sign < 0) return -((-*this) + (-b));
    intx c; c.data.clear();
    unsigned long long carry = 0;
    for (int i = 0; i < size() || i < b.size() || carry; i++) {
      carry += (i < size() ? data[i] : 0ULL) +
        (i < b.size() ? b.data[i] : 0ULL);
      c.data.push_back(carry % intx::radix);
      carry /= intx::radix; }
    return c.normalize(sign); }
  intx operator -(const intx& b) const {
    if (sign > 0 && b.sign < 0) return *this + (-b);
    if (sign < 0 && b.sign > 0) return -(-*this + b);
    if (sign < 0 && b.sign < 0) return (-b) - (-*this);
    if (*this < b) return -(b - *this);
    intx c; c.data.clear();
    long long borrow = 0;
    rep(i,0,size()) {
      borrow = data[i] - borrow
                       - (i < b.size() ? b.data[i] : 0ULL);
      c.data.push_back(borrow < 0 ? intx::radix + borrow
                                  : borrow);
      borrow = borrow < 0 ? 1 : 0; }
    return c.normalize(sign); }
  intx operator *(const intx& b) const {
    intx c; c.data.assign(size() + b.size() + 1, 0);
    rep(i,0,size()) {
      long long carry = 0;
      for (int j = 0; j < b.size() || carry; j++) {
        if (j < b.size())
          carry += (long long)data[i] * b.data[j];
        carry += c.data[i + j];
        c.data[i + j] = carry % intx::radix;
        carry /= intx::radix; } }
    return c.normalize(sign * b.sign); }
  friend pair<intx,intx> divmod(const intx& n, const intx& d) {
    assert(!(d.size() == 1 && d.data[0] == 0));
    intx q, r; q.data.assign(n.size(), 0);
    for (int i = n.size() - 1; i >= 0; i--) {
      r.data.insert(r.data.begin(), 0);
      r = r + n.data[i];
      long long k = 0;
      if (d.size() < r.size())
        k = (long long)intx::radix * r.data[d.size()];
      if (d.size() - 1 < r.size()) k += r.data[d.size() - 1];
      k /= d.data.back();
      r = r - abs(d) * k;
      // if (r < 0) for (ll t = 1LL << 62; t >= 1; t >>= 1) {
      //     intx dd = abs(d) * t;
      //     while (r + dd < 0) r = r + dd, k -= t; }
      while (r < 0) r = r + abs(d), k--;
      q.data[i] = k; }
    return pair<intx, intx>(q.normalize(n.sign * d.sign), r); }
  intx operator /(const intx& d) const {
    return divmod(*this,d).first; }
  intx operator %(const intx& d) const {
    return divmod(*this,d).second * sign; } 
  bool iszero() {
      return data.size() == 1 && data[0] == 0; }
  bool isone() {
      return data.size() == 1 && data[0] == 1; } };

template <typename T> bool eq(T a, T b) { return a == b; }
template <typename T> T t_abs(T x) { return (x < T(0)) ? (-x) : x; }
template <> bool eq<double>(double a, double b) { return t_abs<double>(a - b) < 1e-9; }
template <typename T> struct matrix {
    int r, c;
    std::vector<T> dat;
    matrix(int _r, int _c) : r(_r), c(_c) {
        dat = std::vector<T>(r * c, T(0));
    }
    matrix(const matrix& o) : r(o.r), c(o.c), dat(o.dat) { }
    T& operator()(int i, int j) { return dat[i * c + j]; }
    matrix<T> operator +(const matrix& o) {
        matrix<T> res(*this);
        for(int i = 0; i < dat.size(); ++i) {
            res.dat[i] += o.dat[i];
        }
        return res;
    }
    matrix<T> operator -(const matrix& o) {
        matrix<T> res(*this);
        for(int i = 0; i < dat.size() ; ++i) {
            res.dat[i] -= o.dat[i];
        }
        return res;
    }
    matrix<T> operator *(T o) {
        matrix<T> res(*this);
        for(int i = 0; i < dat.size(); ++i) {
            res.dat[i] *= o;
        }
        return res;
    }
    matrix<T> operator *(matrix& o) {
        matrix<T> res(r, o.c);
        for(int i = 0; i < r; ++i) {
            for(int k = 0; k < c; ++k) {
                for(int j = 0; j < o.c; ++j) {
                    res(i, j) += (*this)(i, k) * o(k, j);
                }
            }
        }
        return res;
    }
    matrix<T> pow(long long p) {
        matrix<T> res(r, c), sq(*this);
        for(int i = 0; i < r; ++i) {
            res(i, i) = T(1);
        }
        while(p) {
            if(p & 1) res = res * sq;
            p >>= 1;
            if(p) sq = sq * sq;
        }
        return res;
    }
    matrix<T> transpose() {
        matrix<T> res(c, r);
        for(int i = 0; i < r; ++i) {
            for(int j = 0; j < c; ++j) {
                res(j, i) = (*this)(i, j);
            }
        }
        return res;
    }
    matrix<T> rref(T& det, int& rank) {
        matrix<T> mat(*this);
        det = T(1);
        rank = 0;
        for(int ri = 0, ci = 0; ci < c; ++ci) {
            int k = ri;
            for(int i = k + 1; i < r; ++i) if(t_abs(mat(i, ci)) > t_abs(mat(k, ci))) k = i;
            if(k >= r || eq<T>(mat(k, ci), T(0))) continue;
            if(k != ri) {
                det *= T(-1);
                for(int i = 0; i < c; ++i) std::swap(mat(k, i), mat(ri, i));
            }
            det *= mat(ri, ri);
            rank++;
            T d = mat(ri, ci);
            for(int i = 0; i < c; ++i) mat(ri, i) /= d;
            for(int i = 0; i < r; ++i) {
                T piv = mat(i, ci);
                if(i != ri && !eq<T>(piv, T(0))) {
                    for(int j = 0; j < c; ++j) mat(i, j) -= piv * mat(ri, j);
                }
            }
            ri++;
        }
        return mat;
    }
    matrix<T> inverse() {
        assert(r == c);
        matrix<T> aug(r, 2 * c);
        for(int i = 0; i < r; ++i) {
            for(int j = 0; j < c; ++j) {
                aug(i, j) = (*this)(i, j);
            }
            aug(i, i + c) = T(1);
        }
        T det; int rnk;
        aug = aug.rref(det, rnk);
        if(rnk != c) bail();
        matrix<T> res(r, c);
        for(int i = 0; i < r; ++i) {
            for(int j = 0; j < c; ++j) {
                res(i, j) = aug(i, j + c);
            }
        }
        return res;
    }
    friend std::ostream& operator <<(std::ostream& out, const matrix<T>& o) {
        for(int i = 0; i < o.r; ++i) {
            for(int j = 0; j < o.c; ++j) {
                out << o.dat[i * o.c + j] << ' ';
            }
            out << '\n';
        }
        return out;
    }
};

int gcd(int a, int b) { return b == 0 ? a : gcd(b, a % b); }

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    int N, K; cin >> N >> K;
    vector<ll> p(K);
    for(ll &x : p) cin >> x;
    vector<intx> m(K);
    for(int i = 0; i < K; ++i) {
        string num; cin >> num;
        m[i] = intx(num);
    }
    vector<intx> cumul(N + 1, intx(0));
    for(int i = 0; i < K; ++i) {
        for(ll j = 1; j * p[i] <= N; ++j) {
            cumul[j * p[i]] = cumul[j * p[i]] + m[i];
        }
    }
    vector<int> lgcum(N + 1, 0);
    for(int i = 0; i <= N; ++i) {
        if(cumul[i].iszero()) continue;
        while(!cumul[i].isone()) {
            lgcum[i]++;
            auto res = divmod(cumul[i], intx(2));
            if(res.second.isone()) bail();
            cumul[i] = res.first;
        }
    }
    matrix<double> G(N, N);
    for(int i = 0; i < N; ++i)
        for(int j = 0; j < N; ++j)
            G(i, j) = gcd(i + 1, j + 1);
    matrix<double> H = G.inverse();
    matrix<double> v(N, 1);
    for(int i = 1; i <= N; ++i)
        v(i - 1, 0) = lgcum[i];
    matrix<double> w = H * v;
    int elem = 0;
    vector<int> pi;
    for(int i = 0; i < N; ++i) {
        int k = round(w(i, 0));
        if(k < 0) bail();
        if(abs(w(i, 0) - k) > EPS) bail();
        if(elem + k * (i + 1) > N) bail();
        while(k--) {
            if(i == 0) {
                pi.push_back(elem);
                elem++;
                continue;
            }
            int fst = elem; elem++;
            for(int j = 0; j < i; ++j)
                pi.push_back(elem), elem++;
            pi.push_back(fst);
        }
    }
    if(pi.size() != N) bail();
    for(int x : pi) cout << x + 1 << ' ';
    cout << '\n';
}
