#include<iostream>
#include<vector>
#include<cassert>
using namespace std;
typedef long long ll;

ll gcd(ll a, ll b) { return b == 0 ? a : gcd(b, a % b); }

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    ll N, E; cin >> N >> E;
    vector<vector<ll>> sols(N);
    for(ll k = 1; k <= 2 * N; ++k) {
        ll g = gcd(k % 2 ? k : k / 2, N);
        ll m = N / g, r = k - 1;
        if(k % 2) r /= 2, r %= m;
        else if(m % 2 == 0) continue;
        else r %= m, r *= (m + 1) / 2, r %= m;
        for(ll d = 0; d < N / m; ++d) {
            sols[(d * m + r) % N].push_back(k);
        }
    }
    vector<ll> steps(N, -1);
    for(ll i = 0; i < N; ++i) {
        if(sols[i].size() > 0)
            steps[i] = sols[i][0];
        for(ll x : sols[i])
            steps[i] = min(steps[i], x);
    }
    ll dist = 0;
    for(int i = 0; i < N; ++i) {
        ll s = steps[E % N];
        assert(s != -1);
        if(E - (s - 1) <= 0) {
            cout << dist + E * (E + 1) / 2 << '\n';
            return 0;
        }
        dist += E * s - s * (s - 1) / 2;
        E -= s - 2;
    } 
    ll loopd = 0, loopc = 0, st = E % N, lo = 0, delta = 0, pos = E % N;
    do {
        ll s = steps[pos];
        if(E + delta - (s - 1) <= 0) {
            dist += E * loopd + loopc; E += delta;
            cout << dist + E * (E + 1) / 2 << '\n';
            return 0;
        }
        loopc += delta * s;
        loopc -= s * (s - 1) / 2;
        delta -= s - 1;
        lo = min(lo, delta);
        delta++;
        pos -= s - 2;
        pos = (pos % N + N) % N;
        loopd += s;
    } while(pos != st);
    assert(E > lo);
    if(delta >= 0) {
        cout << "infinity\n";
        return 0;
    }
    ll skip = (E + lo) / -delta;
    dist += skip * loopd * E;
    dist += skip * loopc;
    dist += (skip * (skip - 1) / 2) * loopd * delta;
    E += skip * delta;
    while(true) {
        ll s = steps[E % N];
        if(E - (s - 1) <= 0) {
            cout << dist + E * (E + 1) / 2 << '\n';
            return 0;
        }
        dist += E * s - s * (s - 1) / 2;
        E -= s - 2;
    } 
}
