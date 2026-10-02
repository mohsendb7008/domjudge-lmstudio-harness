#include<iostream>
#include<algorithm>
#include<vector>
using namespace std;
typedef pair<int,int> ii;

int main() {
    int n, h, w;
    cin >> n >> h >> w;
    vector<pair<ii,int>> books(n);
    for(int i = 0; i < n; ++i)
        books[i].second = i;
    for(auto &p : books)
        cin >> p.first.first >> p.first.second;
    int maxh = 0, totw = 0;
    for(auto p : books)
        maxh = max(maxh, p.first.first),
        totw += p.first.second;
    sort(books.begin(), books.end());
    vector<vector<int>> prv(n + 1, vector<int>(h + 1, -1));
    prv[0][0] = -2;
    int maxuse = 0;
    for(int i = 1; i <= n; ++i) {
        int curh = books[i - 1].first.first;
        int curw = books[i - 1].first.second;
        for(int j = 0; j <= h; ++j) {
            if(prv[i - 1][j] != -1 && curh <= h) {
                prv[i][j] = j;
                if(j != totw)
                    maxuse = max(maxuse, j);
                continue; 
            }
            if(j < curw) continue;
            if(prv[i - 1][j - curw] == -1) continue;
            prv[i][j] = j - curw;
            if(j != totw)
                maxuse = max(maxuse, j);
        }
        if(i < n && maxh > h) continue;
        int left = w - curh;
        if(left < 0 || maxuse == 0) continue;
        if(maxuse + left < totw) continue;
        vector<int> up, side;
        int pos = maxuse;
        for(int j = i; j > 0; --j) {
            int nxt = prv[j][pos];
            int ind = books[j - 1].second;
            if(nxt == pos) up.push_back(ind);
            else side.push_back(ind), pos = nxt;
        }
        for(int j = i + 1; j <= n; ++j) {
            int ind = books[j - 1].second;
            up.push_back(ind);
        }
        cout << "upright ";
        for(int x : up) cout << x + 1 << ' ';
        cout << '\n';
        cout << "stacked ";
        for(int x : side) cout << x + 1 << ' ';
        cout << '\n';
        return 0;
    }
    cout << "impossible\n";
}
